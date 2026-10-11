"""Full-screen terminal presentation for the provider-independent chat service."""
import asyncio
import re
import sys
from threading import Event

from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import ConditionalContainer, Float, FloatContainer, HSplit, Layout, VSplit
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, Label, TextArea

from .chat import ChatService
from .chat_workflow import HELP
from .domain import ForgeError
from .progress import with_progress, format_progress


ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))')


def display(text: str) -> str:
    """Keep provider text as text, never as terminal control sequences."""
    text = ANSI.sub('', text)
    return ''.join(char for char in text if char in '\n\t' or (char.isprintable() and char != '\x7f'))


class SlashCompleter(Completer):
    commands = list(dict.fromkeys(['/request', *re.findall(r'^  (/[^ ]+)', HELP, re.M)]))

    descriptions = {}
    for line in HELP.splitlines():
        if line.startswith('  /'):
            descriptions.setdefault(line.strip().split()[0], re.split(r' {2,}', line.strip())[-1])

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text in self.commands or not text.startswith('/') or any(char.isspace() for char in text):
            return
        for command in self.commands:
            if command.startswith(text) and command != text:
                yield Completion(command, start_position=-len(text), display_meta=self.descriptions.get(command, ''))


class ConversationLexer(Lexer):
    def __init__(self, ui):
        self.ui = ui

    def lex_document(self, document):
        styles = list(self.ui.conversation_styles)
        return lambda row: [(styles[row] if row < len(styles) else 'class:assistant', document.lines[row])]


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
        self.action_choices = None
        self.action_index = 0
        self.action_title = ''
        self.last_failed_command = None
        self.plan_visible = False
        self.live_events = []
        self.conversation_styles = []
        self.notice = 'Enter sends. Alt+Enter adds a line. /help lists actions.'
        self.history = TextArea(read_only=True, scrollbar=True, wrap_lines=False, width=Dimension.exact(28),
                                style='class:history')
        self.conversation = TextArea(read_only=True, scrollbar=True, wrap_lines=True, style='class:conversation', lexer=ConversationLexer(self))
        self.composer = TextArea(multiline=True, height=Dimension(min=3, max=6, preferred=3),
                                 wrap_lines=True, completer=SlashCompleter(), complete_while_typing=True, read_only=Condition(lambda: self.busy or self.request_choices is not None), style='class:composer')
        self.request_picker = TextArea(read_only=True, scrollbar=True, wrap_lines=False,
                                       height=Dimension(min=3, max=8), style='class:composer')
        self.action_picker = TextArea(read_only=True, scrollbar=True, wrap_lines=False, height=Dimension(min=3, max=6), style='class:composer')
        self.plan_screen = TextArea(read_only=True, scrollbar=True, wrap_lines=True, height=Dimension(min=4, max=12), style='class:conversation')
        keys = self._keys()
        body = VSplit([
            ConditionalContainer(Frame(self.history, title='Saved chats'),
                                 filter=Condition(lambda: self.app.output.get_size().columns >= 85)),
            HSplit([Frame(self.conversation, title=lambda: display(self.current['title']) if self.current else 'New chat'),
                    Label(lambda: self.context_indicator(), style='class:workflow'),
                    Label(lambda: self.usage_indicator(), style='class:status'),
                    Label(lambda: display('Working… Ctrl+X requests a stop.' if self.busy else
                                          self.current.get('workflow_hint', '') if self.current else
                                          'Start: /start. New idea: /request. Resume or retry: /next.'),
                          style='class:workflow'),
                    ConditionalContainer(
                        Frame(Label(lambda: self.activity_text() + ('\n\n' + '\n'.join(self.live_events[-6:]) if self.live_events else ''), style='class:activity'), title='Activity'),
                        filter=Condition(lambda: self.activity is not None or self.busy)),
                    ConditionalContainer(Frame(self.request_picker, title='Choose a request · ↑/↓ select · Enter confirm · Esc cancel'),
                                         filter=Condition(lambda: self.request_choices is not None)),
                    ConditionalContainer(Frame(self.plan_screen, title='Plan review · Tab to scroll · /approve starts coding · Esc closes'), filter=Condition(lambda: self.plan_visible)),
                    ConditionalContainer(Frame(self.action_picker, title=lambda: self.action_title + ' · ↑/↓ · Enter · Esc'), filter=Condition(lambda: self.action_choices is not None)),
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
        # TextArea provides completion state but does not install a visible popup.
        root = FloatContainer(content=root, floats=[
            Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=8, scroll_offset=1))])
        self.app = Application(layout=Layout(root, focused_element=self.composer), key_bindings=keys,
                               full_screen=True, mouse_support=True, input=input, output=output,
                               refresh_interval=0.25,
                               style=Style.from_dict({
                                   '': 'bg:#090b16 #ddd9f4',
                                   'header': 'bg:#22112e #ff61d8 bold',
                                   'footer': 'bg:#11182a #58e8ff',
                                   'status': 'bg:#090b16 #b6a6d4',
                                   'workflow': 'bg:#090b16 #7dfcc3',
                                   'activity': 'bg:#10172a #f5d779',
                                   'history': 'bg:#0c1021 #aa91c9',
                                   'conversation': 'bg:#090d1b #ddd9f4',
                                   'user': '#58e8ff',
                                   'assistant': '#ddd9f4',
                                   'workflow-text': '#7dfcc3',
                                   'composer': 'bg:#14132b #58e8ff',
                                   'frame.border': '#7952a8',
                                   'frame.label': '#ff61d8 bold',
                                   'scrollbar.background': 'bg:#14132b',
                                   'scrollbar.button': 'bg:#7952a8',
                                   'scrollbar.arrow': '#58e8ff',
                                   'completion-menu.completion': 'bg:#14132b #58e8ff',
                                   'completion-menu.completion.current': 'bg:#ff61d8 #090b16 bold',
                                   'completion-menu.meta.completion': 'bg:#14132b #b6a6d4',
                                   'completion-menu.meta.completion.current': 'bg:#ff61d8 #090b16',
                                   'completion-menu.scrollbar.background': 'bg:#14132b',
                                   'completion-menu.scrollbar.button': 'bg:#58e8ff',
                               }))
        self.refresh_history()
        if resume:
            self.open_session(resume)
        else:
            self.render()

    def _keys(self) -> KeyBindings:
        keys = KeyBindings()
        idle = Condition(lambda: not self.busy and self.request_choices is None and self.action_choices is None)
        picking = Condition(lambda: self.request_choices is not None and not self.busy)

        actions = Condition(lambda: self.action_choices is not None and not self.busy)

        @keys.add('up', filter=actions, eager=True)
        @keys.add('down', filter=actions, eager=True)
        def action_move(event):
            self.action_index = max(0, min(len(self.action_choices) - 1,
                                          self.action_index + (1 if event.key_sequence[0].key == 'down' else -1)))
            self.render_actions()

        @keys.add('enter', filter=actions, eager=True)
        def action_select(event):
            event.app.create_background_task(self.accept_action())

        @keys.add('escape', filter=actions, eager=True)
        def action_cancel(event):
            self.close_actions()

        @keys.add('escape', filter=Condition(lambda: self.plan_visible) & idle, eager=True)
        def plan_close(event):
            self.plan_visible = False
            event.app.layout.focus(self.composer)
            event.app.invalidate()

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
                if self.composer.buffer.complete_state:
                    self.accept_completion()
                else:
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

        @keys.add('tab', filter=has_focus(self.composer) & idle & Condition(lambda: self.composer.buffer.complete_state is not None), eager=True)
        def complete_command(event):
            self.accept_completion()

        @keys.add('tab', filter=~picking & ~actions & Condition(lambda: self.composer.buffer.complete_state is None))
        def next_pane(event):
            focus_next(event)

        @keys.add('s-tab', filter=~picking & ~actions)
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

    def accept_completion(self):
        state = self.composer.buffer.complete_state
        if state:
            completion = state.current_completion or state.completions[0]
            self.composer.buffer.apply_completion(completion)

    def refresh_history(self) -> None:
        self.sessions = self.service.list()
        self.history.text = '\n'.join(('› ' if self.current and s['id'] == self.current['id'] else '  ') +
                                      display(s['title']).replace('\n', ' ') for s in self.sessions) or 'No saved chats yet'

    def open_session(self, session: str) -> None:
        if self.busy:
            return
        self.close_request_picker()
        self.close_actions()
        self.plan_visible = False
        self.last_failed_command = None
        try:
            self.current = self.service.get(session)
            self.live_events = []
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
        self.close_actions()
        self.plan_visible = False
        self.last_failed_command = None
        self.current = None
        self.live_events = []
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

    def context_indicator(self):
        if not self.current:
            return 'Request: none · Stage: new chat'
        request = self.current.get('request_path') or 'none'
        slug = request.split('/')[-2] if request != 'none' else request
        run = self.current.get('workflow_run')
        return display(f'Request: {slug} · Stage: {self.current.get("run_status") or "chat"}' +
                       (f' · Run: {run.split("/")[-1]}' if run else ''))

    def usage_indicator(self):
        snapshots = [self.current.get('progress'), self.current.get('run_progress')] if self.current else []
        sent = [s for s in snapshots if s and s.get('last_prompt_bytes') is not None]
        latest = self.activity if self.busy else max(sent, key=lambda s: s.get('last_prompt_at', s['updated_at']), default=None)
        size = latest.get('last_prompt_bytes') if latest else None
        prompt = f'{size:,}/{self.service.config.max_prompt_bytes:,} bytes' if size is not None else 'not sent yet'
        valid = [s for s in snapshots if s]
        incoming = sum(s['usage']['input_tokens'] for s in valid)
        outgoing = sum(s['usage']['output_tokens'] for s in valid)
        reports = sum(s['usage']['input_reports'] + s['usage']['output_reports'] for s in valid)
        input_reports = sum(s['usage']['input_reports'] for s in valid)
        output_reports = sum(s['usage']['output_reports'] for s in valid)
        tokens = ((f'{incoming:,}' if input_reports else 'unavailable') + ' in / ' +
                  (f'{outgoing:,}' if output_reports else 'unavailable') + ' out (reported)') if reports else 'unavailable'
        return f'Last prompt: {prompt} · Tokens: {tokens}'

    def show_actions(self, title, choices):
        self.action_title, self.action_choices, self.action_index = title, choices, 0
        self.render_actions()
        self.app.layout.focus(self.action_picker)

    def render_actions(self):
        self.action_picker.text = '\n'.join(('› ' if index == self.action_index else '  ') + display(item['label'])
                                            for index, item in enumerate(self.action_choices))
        self.action_picker.buffer.cursor_position = self.action_picker.document.translate_row_col_to_index(self.action_index, 0)
        self.app.invalidate()

    def close_actions(self):
        self.action_choices = None
        self.app.layout.focus(self.composer)
        self.app.invalidate()

    async def accept_action(self):
        if not self.action_choices or self.busy:
            return
        action = self.action_choices[self.action_index]
        self.close_actions()
        if action.get('request'):
            self.busy = True
            try:
                if self.current is None:
                    self.current = await asyncio.to_thread(self.service.new)
                self.current = await asyncio.to_thread(self.service.choose_request, self.current['id'], action['request'])
                self.composer.text = '/status' if self.current.get('workflow_run') else '/prepare'
                self.notice = 'Request selected. Follow the next step above.'
                self.plan_visible = False
                self.refresh_history()
                self.render()
            except (ForgeError, OSError) as exc:
                self.notice = display(str(exc))
                self.app.invalidate()
            finally:
                self.busy = False
        elif action.get('open'):
            self.open_session(action['open'])
        elif action.get('edit'):
            self.composer.buffer.set_document(Document(action['edit'], len(action['edit'])), bypass_readonly=True)
            self.notice = 'Enter the value, then press Enter to save.'
        elif action.get('retry'):
            await self.send(retry=True)
        else:
            self.composer.text = action['command']
            await self.send()

    def show_recovery(self):
        choices = []
        if self.current and self.current.get('pending_message'):
            choices.append({'label': 'Retry pending model reply', 'retry': True})
        elif self.last_failed_command and self.last_failed_command.split()[0] in {'/start', '/next', '/prepare', '/discover', '/plan'}:
            retry = '/next' if self.last_failed_command.split()[0] in {'/start', '/next', '/prepare', '/discover'} else self.last_failed_command
            choices.append({'label': 'Retry ' + retry, 'command': retry})
        elif self.current and self.current.get('run_status') == 'discovering':
            choices.append({'label': 'Continue preparation', 'command': '/next'})
        elif self.current and self.current.get('run_status') == 'ready_to_plan':
            choices.append({'label': 'Continue planning', 'command': '/next'})
        elif self.current and self.current.get('run_status') in {'planned', 'interrupted', 'executing', 'turn_limit'}:
            choices.append({'label': 'Review plan before resuming', 'command': '/run'})
        choices.extend([{'label': 'Adjust timeout', 'edit': '/settings timeout '},
                        {'label': 'Export session logs', 'command': '/logs'}])
        self.show_actions('Recovery actions', choices)

    def show_plan(self):
        if not self.current or not self.current.get('reviewed_plan'):
            self.notice = 'Use /run to display the plan before opening /review.'
            return
        from .audit import Audit
        run = Audit.open(self.service.workspace, self.current['workflow_run'])
        self.plan_screen.text = display(run.read('plan.md'))
        self.plan_screen.buffer.cursor_position = 0
        self.plan_visible = True
        self.app.invalidate()

    async def local_command(self, message):
        parts = message.split(maxsplit=1)
        command, value = parts[0].lower(), parts[1] if len(parts) > 1 else ''
        if command == '/settings':
            if value:
                result = await asyncio.to_thread(self.service.settings, self.current['id'] if self.current else None, value)
                if result['new_chat_required']:
                    self.busy = False
                    self.new_chat()
                    self.busy = True
                self.notice = result['message']
                self.composer.text = ''
            else:
                result = self.service.settings(None)
                self.show_actions('Settings', [{'label': f'{field}: {setting}', 'edit': f'/settings {field} '}
                                              for field, setting in result['values'].items()])
            return True
        if command == '/history':
            results = await asyncio.to_thread(self.service.history, value)
            if results:
                self.show_actions('History · up to 50 chats and requests',
                                  [{'label': item['kind'].title() + ': ' + item['title'] + (' · ' + item['snippet'] if item['snippet'] else ''),
                                    **({'open': item['id']} if item['kind'] == 'chat' else {'request': item['request']})} for item in results])
            else:
                self.notice = 'No saved conversations match. Try /history with another query.'
            return True
        if command == '/recover':
            self.show_recovery()
            return True
        if command == '/review':
            self.show_plan()
            return True
        return False

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
                    '  /start     Prepare your request and build its plan\n'
                    '             Answer any blocking questions as they appear\n'
                    '             Review the plan when it is ready\n'
                    '  /approve   Approve this plan and start coding\n'
                    '  /runs      Continue an existing coding run\n'
                    '  /next      Continue or retry the saved step\n'
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
        styles = []
        if self.current:
            for index, message in enumerate(self.current['messages']):
                if index:
                    styles.append('class:assistant')
                role = ('class:user' if message['role'] == 'user' else
                        'class:workflow-text' if message['content'].startswith('Forge workflow') else 'class:assistant')
                block = ('You' if message['role'] == 'user' else 'Forge') + '\n' + display(message['content'])
                styles.extend([role] * len(block.split('\n')))
            if self.current['pending_message']:
                styles.extend(['class:user'] * (2 + len(display(self.current['pending_message']).split('\n'))))
        self.conversation_styles = styles
        self.conversation.text = text
        self.conversation.buffer.cursor_position = len(text) if self.current else 0
        self.app.invalidate()

    async def send(self, *, retry: bool = False, skip_picker: bool = False) -> None:
        if self.busy or self.request_choices is not None or self.action_choices is not None:
            return
        message = self.composer.text.strip()
        if not retry and message and message.split(maxsplit=1)[0].lower() in {'/settings', '/history', '/recover', '/review'}:
            self.busy = True
            try:
                await self.local_command(message)
            except (ForgeError, OSError, ValueError) as exc:
                self.notice = display(str(exc))
            finally:
                self.busy = False
                self.render()
            return
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
        self.live_events = []
        loop = asyncio.get_running_loop()
        def update_activity(snapshot):
            if self.busy and generation == self.activity_generation:
                self.activity = snapshot
                entry = display(snapshot.get('updated_at', '')[11:19] + ' · ' + snapshot.get('action', 'Working'))
                if not self.live_events or self.live_events[-1] != entry:
                    self.live_events.append(entry)
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
            if command:
                self.current = dict(self.current, messages=[*self.current['messages'], {'role': 'user', 'content': message}])
            self.render()
            if command:
                self.current = await asyncio.to_thread(with_progress, on_progress, self.service.command, self.current['id'], message,
                                                      cancelled=self.stop_requested.is_set)
                self.notice = ('Action could not finish. See the details above.' if self.current.get('command_error')
                               else 'Progress saved. Follow the next step above, or ask your model for help.')
                if self.current.get('command_error'):
                    self.last_failed_command = message
                if self.current.get('reviewed_plan') and (message.split()[0].lower() in {'/start', '/next', '/plan', '/run', '/answer'} or not message.startswith('/')):
                    self.show_plan()
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
            self.last_failed_command = message if command else None
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
                if not self.current.get('reviewed_plan'):
                    self.plan_visible = False
                self.activity = ((self.current.get('run_progress') or self.current.get('progress'))
                                 if command else self.current.get('progress'))
            self.partial_reply = ''
            self.busy = False
            self.refresh_history()
            self.render()
            if ('timed out' in self.notice.lower() or (self.current and 'timed out' in (self.current.get('command_error') or '').lower())):
                self.show_recovery()
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
