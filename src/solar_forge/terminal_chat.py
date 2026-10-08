"""Full-screen terminal presentation for the provider-independent chat service."""
import asyncio
import re
import sys

from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, VSplit
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, Label, TextArea

from .chat import ChatService
from .domain import ForgeError


ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))')


def display(text: str) -> str:
    """Keep provider text as text, never as terminal control sequences."""
    text = ANSI.sub('', text)
    return ''.join(char for char in text if char in '\n\t' or (char.isprintable() and char != '\x7f'))


class TerminalChat:
    def __init__(self, service: ChatService, *, resume: str | None = None, input=None, output=None):
        self.service = service
        self.current = None
        self.sessions = []
        self.busy = False
        self.exit_requested = False
        self.notice = 'Enter sends. Alt+Enter adds a line. Ctrl+N starts a new chat.'
        self.history = TextArea(read_only=True, scrollbar=True, wrap_lines=False, width=Dimension.exact(28),
                                style='class:history')
        self.conversation = TextArea(read_only=True, scrollbar=True, wrap_lines=True, style='class:conversation')
        self.composer = TextArea(multiline=True, height=Dimension(min=3, max=6, preferred=3),
                                 wrap_lines=True, read_only=Condition(lambda: self.busy), style='class:composer')
        keys = self._keys()
        body = VSplit([
            ConditionalContainer(Frame(self.history, title='Saved chats'),
                                 filter=Condition(lambda: self.app.output.get_size().columns >= 85)),
            HSplit([Frame(self.conversation, title=lambda: display(self.current['title']) if self.current else 'New chat'),
                    Label(lambda: display(self.notice), style='class:status'),
                    Frame(self.composer, title='Message · Enter send / Alt+Enter new line')]),
        ], padding=1)
        root = HSplit([
            Label(lambda: ' Solar Forge  |  ' + display(self.service.workspace.root.name) + '  |  ' +
                  display(self.current['provider'] + ' / ' + self.current['model'] if self.current else
                          self.service.config.kind + ' / ' + self.service.config.model), style='class:header'),
            body,
            Label(' Ctrl+N New  Ctrl+L History  Ctrl+R Retry  Tab Next pane  PgUp/PgDn Scroll  Ctrl+Q Quit',
                  style='class:footer'),
        ])
        self.app = Application(layout=Layout(root, focused_element=self.composer), key_bindings=keys,
                               full_screen=True, mouse_support=True, input=input, output=output,
                               style=Style.from_dict({'header': 'bg:#c4e29c #182119 bold',
                                   'footer': 'bg:#252e22 #c4e29c', 'status': '#aebb9f',
                                   'history': 'bg:#111412 #919b91', 'conversation': 'bg:#161817 #e7ebe6',
                                   'composer': 'bg:#20261f #e7ebe6', 'frame.border': '#637951',
                                   'frame.label': '#c4e29c bold'}))
        self.refresh_history()
        if resume:
            self.open_session(resume)
        else:
            self.render()

    def _keys(self) -> KeyBindings:
        keys = KeyBindings()
        idle = Condition(lambda: not self.busy)

        @keys.add('enter', filter=has_focus(self.composer), eager=True)
        def send(event):
            if not self.busy:
                event.app.create_background_task(self.send())

        @keys.add('escape', 'enter', filter=has_focus(self.composer) & idle)
        @keys.add('c-j', filter=has_focus(self.composer) & idle)
        def newline(event):
            self.composer.buffer.insert_text('\n')

        @keys.add('enter', filter=has_focus(self.history), eager=True)
        def select(event):
            row = self.history.document.cursor_position_row
            if not self.busy and row < len(self.sessions):
                self.open_session(self.sessions[row]['id'])
                event.app.layout.focus(self.composer)

        @keys.add('c-n')
        def new(event):
            self.new_chat()

        @keys.add('c-r')
        def retry(event):
            if not self.busy:
                event.app.create_background_task(self.send(retry=True))

        @keys.add('c-l')
        def history(event):
            if not self.busy:
                # On narrow terminals make the session list the main scroll pane.
                if self.app.output.get_size().columns < 85:
                    self.conversation.text = 'Saved chats\n\n' + '\n'.join(
                        f'{i}. {display(s["title"])}\n   {s["id"]}' for i, s in enumerate(self.sessions, 1))
                    self.notice = 'Use /open NUMBER in the composer to reopen a chat.'
                    self.app.layout.focus(self.composer)
                else:
                    self.app.layout.focus(self.history)

        @keys.add('tab')
        def next_pane(event):
            focus_next(event)

        @keys.add('s-tab')
        def previous_pane(event):
            focus_previous(event)

        @keys.add('c-q')
        @keys.add('c-c')
        @keys.add('c-d')
        def quit(event):
            if self.busy:
                self.exit_requested = True
                self.notice = 'Closing after the active reply is saved…'
                self.app.invalidate()
            else:
                event.app.exit()
        return keys

    def refresh_history(self) -> None:
        self.sessions = self.service.list()
        self.history.text = '\n'.join(('› ' if self.current and s['id'] == self.current['id'] else '  ') +
                                      display(s['title']).replace('\n', ' ') for s in self.sessions) or 'No saved chats yet'

    def open_session(self, session: str) -> None:
        if self.busy:
            return
        try:
            self.current = self.service.get(session)
            self.composer.text = ''
            self.notice = ('Reply pending. Ctrl+R retries this saved message.' if self.current['pending_message']
                           else 'Saved conversation reopened.')
            self.refresh_history()
            self.render()
        except (ForgeError, OSError) as exc:
            self.notice = display(str(exc))
            self.app.invalidate()

    def new_chat(self) -> None:
        if self.busy:
            return
        self.current = None
        self.composer.text = ''
        self.notice = 'New chat. Describe your idea or ask a project question.'
        self.refresh_history()
        self.render()
        self.app.layout.focus(self.composer)

    def render(self) -> None:
        if not self.current:
            text = ('What are we building?\n\n'
                    'Think through an idea, explore your project, or shape your next request.\n\n'
                    'Your configured model receives project guidance and request.md if present.\n'
                    'Conversations are saved in agentic_audit.\n\n'
                    'Tab moves between history, conversation, and composer.\n'
                    'Chat helps plan; use forge run for approved implementation.')
        else:
            text = '\n\n'.join(('You' if m['role'] == 'user' else 'Forge') + '\n' + display(m['content'])
                               for m in self.current['messages'])
            if self.current['pending_message']:
                text += '\n\nYou (reply pending)\n' + display(self.current['pending_message'])
        self.conversation.text = text
        self.conversation.buffer.cursor_position = len(text)
        self.app.invalidate()

    async def send(self, *, retry: bool = False) -> None:
        if self.busy:
            return
        message = self.composer.text.strip()
        if not retry and message.startswith('/open '):
            try:
                number = int(message.removeprefix('/open ').strip())
                if not 1 <= number <= len(self.sessions):
                    raise ValueError()
                self.open_session(self.sessions[number - 1]['id'])
            except ValueError:
                self.notice = 'Use /open NUMBER from the saved-chat list (Ctrl+L).'
                self.app.invalidate()
            return
        if not retry and not message:
            return
        if retry and (not self.current or not self.current['pending_message']):
            self.notice = 'No pending message to retry.'
            self.app.invalidate()
            return
        if not retry and self.current and self.current['pending_message']:
            self.notice = 'Retry the saved message with Ctrl+R, or start a new chat with Ctrl+N.'
            self.app.invalidate()
            return
        self.busy = True
        self.notice = 'Your model is thinking…'
        try:
            if self.current is None:
                self.current = self.service.new()
            if not retry:
                self.current['pending_message'] = message
                self.composer.buffer.set_document(Document(''), bypass_readonly=True)
            self.render()
            self.current = await asyncio.to_thread(self.service.send, self.current['id'],
                                                  None if retry else message, retry=retry)
            self.notice = 'Reply saved. Enter sends your next message.'
        except (ForgeError, OSError) as exc:
            self.notice = display(str(exc)) + '  Ctrl+R retries; Ctrl+N starts a new chat.'
            if self.current:
                self.current = self.service.get(self.current['id'])
            if not retry and (not self.current or not self.current['pending_message']):
                self.composer.buffer.set_document(Document(message, len(message)), bypass_readonly=True)
        except Exception:
            self.notice = 'Reply failed. Inspect the audit and use Ctrl+R to retry.'
            if self.current:
                self.current = self.service.get(self.current['id'])
        finally:
            self.busy = False
            self.refresh_history()
            self.render()
            if self.exit_requested and self.app.is_running:
                self.app.exit()

    async def run(self) -> None:
        await self.app.run_async()


def run_terminal_chat(service: ChatService, *, resume: str | None = None) -> None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ForgeError('forge chat needs an interactive terminal. Run it directly in your terminal.')
    ui = TerminalChat(service, resume=resume)
    asyncio.run(ui.run())
    if ui.current:
        print('Chat saved: ' + ui.current['id'])
