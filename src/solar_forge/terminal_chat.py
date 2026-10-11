"""Full-screen terminal presentation for the provider-independent chat service."""
import asyncio
import re
import sys
from threading import Event

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
from .progress import with_progress, format_progress


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
        self.stop_requested = Event()
        self.partial_reply = ''
        self.activity = None
        self.activity_generation = 0
        self.exit_requested = False
        self.request_choices = None
        self.request_choice_index = 0
        self.request_command = ''
        self.notice = 'Enter sends. Alt+Enter adds a line. /help lists actions.'
        self.history = TextArea(read_only=True, scrollbar=True, wrap_lines=False, width=Dimension.exact(28),
                                style='class:history')
        self.conversation = TextArea(read_only=True, scrollbar=True, wrap_lines=True, style='class:conversation')
        self.composer = TextArea(multiline=True, height=Dimension(min=3, max=6, preferred=3),
                                 wrap_lines=True, read_only=Condition(lambda: self.busy or self.request_choices is not None), style='class:composer')
        self.request_picker = TextArea(read_only=True, scrollbar=True, wrap_lines=False,
                                       height=Dimension(min=3, max=8), style='class:composer')
        keys = self._keys()
        body = VSplit([
            ConditionalContainer(Frame(self.history, title='Saved chats'),
                                 filter=Condition(lambda: self.app.output.get_size().columns >= 85)),
            HSplit([Frame(self.conversation, title=lambda: display(self.current['title']) if self.current else 'New chat'),
                    Label(lambda: display('Working… Ctrl+X requests a stop.' if self.busy else
                                          self.current.get('workflow_hint', '') if self.current else
                                          'Start: /request or /prepare. Continue: /runs. Help: /help.'),
                          style='class:workflow'),
                    ConditionalContainer(
                        Frame(Label(lambda: self.activity_text(), style='class:activity'), title='Activity'),
                        filter=Condition(lambda: self.activity is not None or self.busy)),
                    ConditionalContainer(Frame(self.request_picker, title='Choose a request · ↑/↓ select · Enter confirm · Esc cancel'),
                                         filter=Condition(lambda: self.request_choices is not None)),
                    Label(lambda: display(self.notice), style='class:status'),
                    Frame(self.composer, title='Message · Enter send / Alt+Enter new line')]),
        ], padding=1)
        root = HSplit([
            Label(lambda: ' Solar Forge  |  ' + display(self.service.workspace.root.name) + '  |  ' +
                  display(self.current['provider'] + ' / ' + self.current['model'] if self.current else
                          self.service.config.kind + ' / ' + self.service.config.model), style='class:header'),
            body,
            Label(lambda: (' /help Actions  Ctrl+L History  Ctrl+R Retry  Ctrl+X Stop  Ctrl+Q Quit'
                           if self.app.output.get_size().columns < 85 else
                           ' /help Actions  Ctrl+N New  Ctrl+L History  Ctrl+R Retry  Ctrl+X Stop  Tab Next pane  Ctrl+Q Quit'),
                  style='class:footer'),
        ])
        self.app = Application(layout=Layout(root, focused_element=self.composer), key_bindings=keys,
                               full_screen=True, mouse_support=True, input=input, output=output,
                               refresh_interval=0.25,
                               style=Style.from_dict({'header': 'bg:#c4e29c #182119 bold',
                                   'footer': 'bg:#252e22 #c4e29c', 'status': '#aebb9f', 'workflow': '#c4e29c',
                                   'activity': 'bg:#20261f #c4e29c',
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
        idle = Condition(lambda: not self.busy and self.request_choices is None)
        picking = Condition(lambda: self.request_choices is not None and not self.busy)

        @keys.add('up', filter=picking, eager=True)
        def request_up(event):
            self.move_request_choice(-1)

        @keys.add('down', filter=picking, eager=True)
        def request_down(event):
            self.move_request_choice(1)

        @keys.add('enter', filter=picking, eager=True)
        def request_confirm(event):
            event.app.create_background_task(self.accept_request_choice())

        @keys.add('escape', filter=picking, eager=True)
        def request_cancel(event):
            self.close_request_picker()
            self.notice = 'Request selection cancelled. Your command is kept in the composer.'
            self.app.invalidate()

        @keys.add('enter', filter=has_focus(self.composer) & idle, eager=True)
        def send(event):
            if not self.busy:
                event.app.create_background_task(self.send())

        @keys.add('escape', 'enter', filter=has_focus(self.composer) & idle)
        @keys.add('c-j', filter=has_focus(self.composer) & idle)
        def newline(event):
            self.composer.buffer.insert_text('\n')

        @keys.add('enter', filter=has_focus(self.history) & idle, eager=True)
        def select(event):
            row = self.history.document.cursor_position_row
            if not self.busy and row < len(self.sessions):
                self.open_session(self.sessions[row]['id'])
                event.app.layout.focus(self.composer)

        @keys.add('c-n')
        def new(event):
            self.new_chat()

        @keys.add('c-r', filter=idle)
        def retry(event):
            if not self.busy:
                event.app.create_background_task(self.send(retry=True))

        @keys.add('c-l', filter=idle)
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

        @keys.add('tab', filter=~picking)
        def next_pane(event):
            focus_next(event)

        @keys.add('s-tab', filter=~picking)
        def previous_pane(event):
            focus_previous(event)

        @keys.add('c-x')
        def stop(event):
            if self.busy:
                self.stop_requested.set()
                self.notice = 'Stop requested. Checks can stop now; model reads may finish or time out first.'
                self.app.invalidate()

        @keys.add('c-q')
        @keys.add('c-c')
        @keys.add('c-d')
        def quit(event):
            if self.busy:
                self.exit_requested = True
                self.notice = 'Closing after the active action and its progress are saved…'
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
        self.close_request_picker()
        try:
            self.current = self.service.get(session)
            self.activity = self.current.get('run_progress') or self.current.get('progress')
            self.composer.text = ''
            self.notice = ('Reply pending. Ctrl+R retries; /discard-pending lets you edit it.' if self.current['pending_message']
                           else 'Saved conversation reopened.')
            self.refresh_history()
            self.render()
        except (ForgeError, OSError) as exc:
            self.notice = display(str(exc))
            self.app.invalidate()

    def new_chat(self) -> None:
        if self.busy:
            return
        self.close_request_picker()
        self.current = None
        self.activity = None
        self.activity_generation += 1
        self.composer.text = ''
        self.notice = 'New chat. Describe your idea or ask a project question.'
        self.refresh_history()
        self.render()
        self.app.layout.focus(self.composer)

    def show_request_picker(self, message: str, choices: list[dict]) -> None:
        self.request_choices = choices
        self.request_command = message
        self.request_choice_index = 0
        self.move_request_choice(0)
        self.notice = 'Choose the request for ' + message + '.'
        self.app.layout.focus(self.request_picker)
        self.app.invalidate()

    def move_request_choice(self, offset: int) -> None:
        if not self.request_choices:
            return
        self.request_choice_index = max(0, min(len(self.request_choices) - 1, self.request_choice_index + offset))
        self.request_picker.text = '\n'.join(
            ('› ' if index == self.request_choice_index else '  ') +
            display(f'{item["title"]} — {item["status"]} · {item["path"]}').replace('\n', ' ')
            for index, item in enumerate(self.request_choices))
        self.request_picker.buffer.cursor_position = self.request_picker.document.translate_row_col_to_index(
            self.request_choice_index, 0)
        self.app.invalidate()

    def close_request_picker(self) -> None:
        self.request_choices = None
        self.request_command = ''
        self.app.layout.focus(self.composer)
        self.app.invalidate()

    async def accept_request_choice(self) -> None:
        if not self.request_choices or self.busy:
            return
        choice = self.request_choices[self.request_choice_index]
        message = self.request_command
        self.close_request_picker()
        self.busy = True
        try:
            if self.current is None:
                self.current = await asyncio.to_thread(self.service.new)
            self.current = await asyncio.to_thread(self.service.choose_request, self.current['id'], choice['path'])
        except (ForgeError, OSError) as exc:
            self.notice = display(str(exc))
            self.render()
            return
        finally:
            self.busy = False
        command = message.split(maxsplit=1)[0].lower()
        if not self.current.get('workflow_run') and command in {'/plan', '/run', '/discover', '/answer', '/changes', '/approve'}:
            self.composer.text = '/prepare'
            self.notice = 'Request selected. Press Enter to prepare it before planning or working on its run.'
            self.refresh_history()
            self.render()
            return
        # Picking a request never approves an existing plan. Show it for review.
        self.composer.text = '/run' if command == '/approve' else message
        await self.send(skip_picker=True)

    def activity_text(self) -> str:
        width = max(12, self.app.output.get_size().columns - (34 if self.app.output.get_size().columns >= 85 else 6))
        if self.activity is None:
            return 'Starting… Ctrl+X requests a stop.'
        # Strip control sequences before clipping so hidden escape bytes cannot
        # eat the visible space or become active terminal commands.
        text = format_progress(self.activity, live=self.busy, width=10000,
                               stop_requested=self.busy and self.stop_requested.is_set())
        return '\n'.join(line if len(line) <= width else line[:width-1] + '…'
                         for line in display(text).splitlines())

    def render(self) -> None:
        if not self.current:
            text = ('What are we building?\n\n'
                    'Ask your model for help, or use these actions:\n\n'
                    '  /request   Write a request, one question at a time\n'
                    '  /prepare   Find questions in the selected request\n'
                    '  /answer    Record answers (use /ask for model advice)\n'
                    '  /plan      Create and review a coding plan\n'
                    '  /approve   Approve this plan and start coding\n'
                    '  /runs      Continue an existing coding run\n'
                    '  /next      Take the next step; approval is still required\n'
                    '  /help      See all actions\n\n'
                    'Use /ask TEXT for advice while drafting or answering.\n'
                    'Requests, project guidance, and selected run details go to your model.\n'
                    'Your conversation and progress are saved in agentic_audit.')
        else:
            text = '\n\n'.join(('You' if m['role'] == 'user' else 'Forge') + '\n' + display(m['content'])
                               for m in self.current['messages'])
            if self.current['pending_message']:
                text += '\n\nYou (reply pending)\n' + display(self.current['pending_message'])
        if self.partial_reply:
            text += '\n\nForge (streaming; not yet complete)\n' + display(self.partial_reply)
        self.conversation.text = text
        self.conversation.buffer.cursor_position = len(text) if self.current else 0
        self.app.invalidate()

    async def send(self, *, retry: bool = False, skip_picker: bool = False) -> None:
        if self.busy or self.request_choices is not None:
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
        if not retry and self.current and self.current['pending_message'] and message not in {'/discard-pending', '/logs'}:
            self.notice = 'Retry with Ctrl+R, or use /discard-pending to edit the saved message.'
            self.app.invalidate()
            return
        if not retry and not skip_picker:
            try:
                choices = self.service.request_options(message, self.current['id'] if self.current else None)
            except (ForgeError, OSError) as exc:
                self.notice = display(str(exc))
                self.app.invalidate()
                return
            if choices is not None:
                if choices:
                    self.show_request_picker(message, choices)
                else:
                    self.notice = 'No existing requests. Use /request TITLE to create one.'
                    self.app.invalidate()
                return
        # /ask explicitly consults the model while a request/answer prompt is active.
        parts = message.split(maxsplit=1)
        asking = not retry and bool(parts) and parts[0].lower() == '/ask'
        if asking:
            question = parts[1].strip() if len(parts) > 1 else ''
            if not question:
                self.notice = 'Use /ask followed by your question.'
                self.app.invalidate()
                return
        command = not retry and not asking and (message.startswith('/') or
                                                bool(self.current and self.current.get('input_mode')))
        self.busy = True
        self.stop_requested.clear()
        self.partial_reply = ''
        self.activity_generation += 1
        generation = self.activity_generation
        self.activity = None
        loop = asyncio.get_running_loop()
        def update_activity(snapshot):
            if self.busy and generation == self.activity_generation:
                self.activity = snapshot
                self.app.invalidate()
        def on_progress(snapshot):
            loop.call_soon_threadsafe(update_activity, snapshot)
        def append_chunk(chunk):
            self.partial_reply += chunk
            self.render()
        def on_chunk(chunk):
            loop.call_soon_threadsafe(append_chunk, chunk)
        self.notice = ('Coding… Your progress and changes are saved in the run audit.' if message == '/approve' else
                       'Working on your request…' if command else 'Your model is thinking…')
        try:
            if self.current is None:
                self.current = self.service.new()
            if not retry and not command:
                self.current['pending_message'] = question if asking else message
            if not retry:
                self.composer.buffer.set_document(Document(''), bypass_readonly=True)
            self.render()
            if command:
                self.current = await asyncio.to_thread(with_progress, on_progress, self.service.command, self.current['id'], message,
                                                      cancelled=self.stop_requested.is_set)
                self.notice = ('Action could not finish. See the details above.' if self.current.get('command_error')
                               else 'Progress saved. Follow the next step above, or ask your model for help.')
                if 'discarded_message' in self.current:
                    # Preserve model-advice semantics even while a wizard is active.
                    draft = '/ask ' + self.current['discarded_message']
                    self.composer.buffer.set_document(Document(draft, len(draft)), bypass_readonly=True)
                    self.notice = 'Pending message discarded and kept in the audit. Edit the draft or enter a workflow command.'

            else:
                self.current = await asyncio.to_thread(with_progress, on_progress, self.service.send, self.current['id'],
                                                      None if retry else question if asking else message, retry=retry, on_chunk=on_chunk,
                                                      cancelled=self.stop_requested.is_set)
                self.notice = 'Reply saved. Enter sends your next message.'
        except (ForgeError, OSError) as exc:
            self.notice = display(str(exc)) + ('  Use /status to check progress.' if command else
                                               '  Ctrl+R retries; /discard-pending lets you edit or continue.')
            if self.current:
                self.current = self.service.get(self.current['id'])
            if not retry and (not self.current or not self.current['pending_message']):
                self.composer.buffer.set_document(Document(message, len(message)), bypass_readonly=True)
        except Exception:
            self.notice = ('Action stopped. Use /status to check saved progress.' if command else
                           'Reply failed. Inspect the audit and use Ctrl+R to retry.')
            if self.current:
                self.current = self.service.get(self.current['id'])
        finally:
            if self.current:
                self.activity = ((self.current.get('run_progress') or self.current.get('progress'))
                                 if command else self.current.get('progress'))
            self.partial_reply = ''
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
