"""Explicit chat actions backed by the same request workflow as the CLI."""
import hashlib
import json
import shlex

from .agent import approve, run
from .audit import Audit
from .domain import Config, ForgeError, Request
from .requests import current_request, request_name, request_path, read_request, write_request
from .providers import Provider
from .workflow import assert_current, discover, plan, plan_digest, prepare, record_answer
from .workspace import Workspace

HELP = '''Work on a request here in chat:
  /request           Create a request, one question at a time
  /request show      Read the selected request
  /save-request      Save the request you have drafted
  /prepare [FILE]    Read the request and find questions (selected request, or the only request bundle)
  /answer            Answer the next question, one at a time
  /answer Q1 TEXT    Save a specific answer
  /plan              Create and display the coding plan
  /run               Display the plan for review or resume an interrupted run
  /approve           Approve the displayed plan and start coding
  /status            Show progress and what to do next
  /changes [FILE]    Review saved file diffs for the selected run
  /runs              List existing coding runs
  /use NUMBER        Continue a run from that list (a run path also works)
  /discover          Retry failed preparation for the selected run
  /next              Take the next step; coding still requires /approve
  /cancel            Leave request drafting, question answering, or plan review
  /ask TEXT          Ask your model for help at any step
  /help              Show these instructions

Ordinary messages go to your model, except while drafting a request or recording
an answer. Use /ask then if you want advice instead of saving an answer.
Paths with spaces can be wrapped in quotes. Commands act on the selected run.
Model replies cannot approve a plan or execute commands.'''

NEXT = {
    'discovering': 'Preparation did not finish. Use /discover to retry.',
    'awaiting_answers': 'Questions need your answers. Use /answer, or /ask for help.',
    'ready_to_plan': 'Ready to create a plan. Use /plan.',
    'planned': 'Plan ready. Use /run to review it before approving coding.',
    'executing': 'Use /run to review and resume this run after its active process finishes.',
    'interrupted': 'Coding stopped. Use /run to review and resume.',
    'turn_limit': 'Turn limit reached. Increase max_turns in settings and reopen chat, or start a new run.',
    'review_required': 'Coding finished. Use /changes to review edits and /ask for help with the suggested checks. Tests have not been run.',
}


def file_hash(text: str | None) -> str | None:
    return hashlib.sha256(text.encode('utf-8')).hexdigest() if text is not None else None


def input_mode(state: dict) -> str | None:
    if state.get('request_draft'):
        return 'request'
    if state.get('answering'):
        return 'answer'
    return None


def workflow_hint(workspace: Workspace, state: dict) -> str:
    if state.get('request_draft'):
        if state['request_draft']['stage'] == 'review':
            return 'Request ready. /save-request saves; /ask helps; /cancel discards.'
        return 'Drafting a request. Enter an answer; /ask helps; /cancel stops.'
    if state.get('answering'):
        return f'Answering {state["answering"]}. Enter your answer, or /ask for help.'
    if state.get('reviewed_plan'):
        return 'Review the plan. /approve starts coding; /ask asks for help.'
    if state.get('workflow_run'):
        try:
            return NEXT.get(Audit.open(workspace, state['workflow_run']).load()['status'], 'Use /status for progress.')
        except (ForgeError, OSError):
            return 'Selected run is unavailable. Use /runs to choose another.'
    return 'Start with /request or /prepare. Use /runs to continue existing work; /help lists commands.'


class ChatWorkflow:
    def __init__(self, workspace: Workspace, config: Config, provider: Provider, chat: Audit, state: dict):
        self.workspace, self.config, self.provider = workspace, config, provider
        self.chat, self.state = chat, state

    def selected(self, value: str = '') -> Audit:
        if value:
            words = shlex.split(value)
            if len(words) != 1:
                raise ForgeError('Use one run number or path. Put paths with spaces in quotes.')
            relative = words[0]
            if relative.isdigit():
                listed = self.state.get('workflow_runs', [])
                number = int(relative)
                if not 1 <= number <= len(listed):
                    raise ForgeError('Use /runs, then /use NUMBER from that list.')
                relative = listed[number - 1]
            audit = Audit.open(self.workspace, relative)
            if audit.load().get('run_kind') == 'chat':
                raise ForgeError('That is a saved conversation. Use /open to reopen chats, or /runs for coding runs.')
            relative = audit.path.relative_to(self.workspace.root).as_posix()
            if relative != self.state.get('workflow_run'):
                self.state.pop('reviewed_plan', None)
                self.state.pop('answering', None)
            self.state['workflow_run'] = relative
            self.state['request_path'] = audit.load()['request_path']
            return audit
        if not self.state.get('workflow_run'):
            raise ForgeError('Choose a run with /runs and /use NUMBER, or start one with /prepare.')
        return Audit.open(self.workspace, self.state['workflow_run'])

    def check_model(self, audit: Audit) -> None:
        state = audit.load()
        if (state.get('provider'), state.get('model')) != (self.config.kind, self.config.model):
            raise ForgeError('This run uses a different model. Reopen forge chat with its --provider and --model, '
                             'or use /prepare to start a run with your current model.')

    def status(self, audit: Audit) -> str:
        state = audit.load()
        text = f'{state["title"]}: {state["status"]}\nRun: {audit.path.relative_to(self.workspace.root).as_posix()}'
        pending = [q for q in state['questions'] if not q.get('answer')]
        if pending:
            text += '\n\nQuestions to answer:\n' + '\n\n'.join(
                f'{q["id"]}: {q["question"]}\nWhy: {q["rationale"]}\nSources: {", ".join(q["sources"])}'
                for q in pending)
        if state['status'] == 'review_required' and (audit.path / 'summary.md').is_file():
            text += '\n\n' + audit.read('summary.md')
            changes = sorted(audit.path.glob('changes/*/metadata.json'))
            if changes:
                text += '\nChanged files:\n' + '\n'.join(dict.fromkeys(
                    json.loads(path.read_text())['path'] for path in changes))
                text += '\nBefore/after files and diffs: ' + str(audit.path.relative_to(self.workspace.root) / 'changes')
        return text + '\n\n' + NEXT.get(state['status'], 'Use /status to check progress.')

    def changes(self, value: str) -> str:
        audit = self.selected()
        words = shlex.split(value) if value else []
        if len(words) > 1:
            raise ForgeError('Use /changes FILE. Put paths with spaces in quotes.')
        chosen = words[0] if words else None
        patches, used = [], 0
        for path in sorted(audit.path.glob('changes/*/metadata.json')):
            name = json.loads(path.read_text())['path']
            if chosen and name != chosen:
                continue
            text = audit.read(path.parent.relative_to(audit.path).as_posix() + '/diff.patch')
            patch = f'File: {name}\n{text}'
            if used + len(patch.encode('utf-8')) > self.config.max_file_bytes:
                patches.append('More changes are saved in the run’s changes/ folder. Use /changes FILE for a smaller view, or open its diff.patch files.')
                break
            patches.append(patch)
            used += len(patch.encode('utf-8'))
        return '\n\n'.join(patches) if patches else 'No saved changes' + (f' for {chosen}.' if chosen else ' yet.')

    def list_runs(self) -> str:
        root = self.workspace.path('agentic_audit', internal=True)
        runs = []
        for path in sorted(root.glob('*/*/state.json'), reverse=True):
            relative = path.parent.relative_to(self.workspace.root).as_posix()
            audit = Audit.open(self.workspace, relative)
            state = audit.load()
            if state.get('run_kind') != 'chat':
                runs.append((relative, state))
        runs.sort(key=lambda item: item[1]['created_at'], reverse=True)
        self.state['workflow_runs'] = [relative for relative, _ in runs]
        if not runs:
            return 'No coding runs yet. Use /request to write a request, then /prepare.'
        return 'Coding runs:\n\n' + '\n'.join(
            f'{i}. {state["title"]} — {state["status"]}\n   {relative}'
            for i, (relative, state) in enumerate(runs, 1)) + '\n\nUse /use NUMBER to continue a run.'

    def start_request(self, title: str) -> str:
        if self.state.get('request_draft'):
            raise ForgeError('A request draft is already open. Continue it, /save-request, or /cancel first.')
        self.state.pop('answering', None)
        self.state.pop('reviewed_plan', None)
        self.state['request_draft'] = {'stage': 'title', 'fields': {}}
        if title:
            return self.respond(title)
        return 'Let’s write your request. Nothing is saved until you enter /save-request.\n\nWhat is the title?\nUse /ask for advice at any step, or /cancel to stop.'

    def respond(self, message: str) -> str:
        if not message.strip():
            raise ForgeError('Enter an answer, or use /ask for help.')
        if len(message.encode('utf-8')) > self.config.max_file_bytes:
            raise ForgeError('Answer is too long for the configured file size limit.')
        draft = self.state.get('request_draft')
        if draft:
            stage = draft['stage']
            if stage == 'review':
                raise ForgeError('Your draft is ready. Use /save-request to save it, /ask for advice, or /cancel.')
            if stage == 'title' and ('\n' in message or '\r' in message or message.strip() == 'Your request title'):
                raise ForgeError('Give your request a title on one line.')
            if stage == 'title':
                name = request_name(message.strip())
                path = request_path(self.workspace, name)
                draft['path'] = name
                draft['before_sha256'] = file_hash(read_request(self.workspace, name) if path.exists() else None)
            stages = ('title', 'description', 'technical_details', 'acceptance_criteria', 'review')
            draft['fields'][stage] = message.strip()
            draft['stage'] = stages[stages.index(stage) + 1]
            prompts = {
                'description': 'What would you like to build or change? Describe who it helps and what it should do.',
                'technical_details': 'What details or constraints should Forge know? If you are unsure, write "Please help me work out the details."',
                'acceptance_criteria': 'How will you know it works? List the results you want, using Alt+Enter for more lines.',
            }
            if draft['stage'] != 'review':
                return prompts[draft['stage']] + '\n\nYour reply is saved in the draft. Use /ask for advice instead.'
            draft['markdown'] = self.request_markdown(draft['fields'])
            Request.parse(draft['markdown'])
            return (draft['markdown'] + f"\nReview your request above. /save-request writes it to {draft['path']}"
                    + (' and replaces the existing file.' if draft['before_sha256'] is not None else '.')
                    + '\nUse /ask for advice, or /cancel to discard this draft.')
        if self.state.get('answering'):
            return self.answer(self.state['answering'] + ' ' + message)
        raise ForgeError('Use /help for commands, or send an ordinary message to ask your model.')

    @staticmethod
    def request_markdown(fields: dict) -> str:
        criteria = '\n'.join(line if line.startswith('- [') else '- [ ] ' + line.removeprefix('- ').strip()
                             for line in fields['acceptance_criteria'].splitlines() if line.strip())
        return (f'# Request: {fields["title"]}\n\n## Description\n{fields["description"]}\n\n'
                f'## Technical Details\n{fields["technical_details"]}\n\n## Acceptance Criteria\n{criteria}\n')

    def save_request(self) -> str:
        draft = self.state.get('request_draft')
        if not draft or draft['stage'] != 'review':
            raise ForgeError('Finish drafting with /request before saving.')
        name = draft['path']
        path = request_path(self.workspace, name)
        current = read_request(self.workspace, name) if path.exists() else None
        if file_hash(current) != draft['before_sha256']:
            raise ForgeError('request.md changed while you were drafting. Your draft is kept; /cancel and start again to avoid replacing someone else’s edits.')
        write_request(self.workspace, name, draft['markdown'])
        self.state['request_path'] = name
        self.state.pop('request_draft', None)
        self.state.pop('workflow_run', None)
        self.state.pop('reviewed_plan', None)
        self.state.pop('answering', None)
        return f'Saved {name}. Use /prepare to find any questions before coding, or ask your model for help.'

    def prepare_request(self, value: str) -> str:
        words = shlex.split(value) if value else [current_request(self.workspace, self.state.get('request_path'))]
        if len(words) != 1:
            raise ForgeError('Use /prepare FILE. Put paths with spaces in quotes.')
        def created(audit):
            self.state['request_path'] = audit.load()['request_path']
            self.state['workflow_run'] = audit.path.relative_to(self.workspace.root).as_posix()
            self.state.pop('reviewed_plan', None)
            self.state.pop('answering', None)
            # Keep the run discoverable in this chat even if the provider call fails.
            self.chat.save(self.state)
        audit = prepare(self.workspace, self.config, words[0], self.provider, on_created=created)
        return self.status(audit)

    def answer(self, value: str) -> str:
        audit = self.selected()
        with audit.lock():
            if not value:
                pending = [q for q in audit.load()['questions'] if not q.get('answer')]
                if not pending:
                    raise ForgeError('No unanswered questions. Use /status to see the next step.')
                q = pending[0]
                self.state['answering'] = q['id']
                return f'{q["id"]}: {q["question"]}\nWhy: {q["rationale"]}\nSources: {", ".join(q["sources"])}\n\nEnter your answer to save it. Use /ask for advice, or /cancel to leave question answering.'
            parts = value.split(maxsplit=1)
            if len(parts) != 2:
                raise ForgeError('Use /answer Q1 YOUR ANSWER, or /answer to go one question at a time.')
            record_answer(audit, parts[0].upper(), parts[1])
            self.state.pop('reviewed_plan', None)
            self.state.pop('answering', None)
        if any(not q.get('answer') for q in audit.load()['questions']):
            return 'Answer saved.\n\n' + self.answer('')
        return 'All answers saved. Use /plan to create your coding plan.'

    def review(self, audit: Audit) -> str:
        state = audit.load()
        if state['status'] not in {'planned', 'executing', 'interrupted', 'turn_limit'}:
            raise ForgeError(NEXT.get(state['status'], 'Create a plan with /plan first.'))
        if state['turns'] >= self.config.max_turns and not state.get('pending_action'):
            raise ForgeError(NEXT['turn_limit'])
        self.check_model(audit)
        assert_current(self.workspace, self.config, audit)
        text = audit.read('plan.md')
        self.state['reviewed_plan'] = {'run': self.state['workflow_run'], 'sha256': file_hash(text)}
        return ('Plan for ' + state['title'] + '\n\n' + text + '\nReview this plan. /approve permits project file edits and starts coding.'
                + ('\nUse /ask to discuss it, /plan to generate a revised plan, or /cancel to leave it unapproved.'
                   if state['status'] == 'planned' else
                   '\nThis resumes saved coding progress. Use /ask to discuss it, or /cancel to leave it paused.'))

    def execute_approved(self) -> str:
        audit = self.selected()
        self.check_model(audit)
        reviewed = self.state.get('reviewed_plan')
        if not reviewed or reviewed['run'] != self.state['workflow_run']:
            raise ForgeError('Display and review the plan with /plan or /run before using /approve.')
        with audit.lock():
            if reviewed['sha256'] != plan_digest(audit):
                self.state.pop('reviewed_plan', None)
                raise ForgeError('The plan changed since you reviewed it. Use /run to read the current plan before approving.')
            assert_current(self.workspace, self.config, audit)
            if audit.load()['status'] == 'planned':
                approve(audit)
            self.state.pop('reviewed_plan', None)
            self.chat.save(self.state)
            run(self.workspace, self.config, audit, self.provider)
        return self.status(audit)

    def dispatch(self, message: str) -> str:
        if not message.startswith('/'):
            return self.respond(message)
        parts = message.split(maxsplit=1)
        command, value = parts[0].lower(), parts[1].strip() if len(parts) > 1 else ''
        if command == '/help':
            return HELP
        if command == '/cancel':
            for key in ('request_draft', 'answering', 'reviewed_plan'):
                self.state.pop(key, None)
            return 'Prompt closed. Existing files and saved progress are kept. No new coding was started. Use /status for progress.'
        if command == '/request':
            if value == 'show':
                return read_request(self.workspace, current_request(self.workspace, self.state.get('request_path')))
            return self.start_request(value)
        if command == '/save-request':
            if value:
                raise ForgeError('Use /save-request without arguments to save your completed draft.')
            return self.save_request()
        if command == '/runs':
            return self.list_runs()
        if command == '/use':
            if not value:
                raise ForgeError('Use /runs, then /use NUMBER to choose a run.')
            return self.status(self.selected(value))
        if command == '/status':
            return self.status(self.selected(value)) if value or self.state.get('workflow_run') else self.list_runs()
        if command == '/changes':
            return self.changes(value)
        if self.state.get('request_draft'):
            raise ForgeError('Finish or /cancel your request draft before starting the coding workflow. Use /ask for advice.')
        if command == '/prepare':
            return self.prepare_request(value)
        if command == '/answer':
            return self.answer(value)
        if command == '/approve':
            if value:
                raise ForgeError('Use /approve without arguments to approve the plan you reviewed.')
            return self.execute_approved()
        if command == '/next':
            if value:
                raise ForgeError('Use /next without arguments.')
            if not self.state.get('workflow_run'):
                return self.prepare_request('')
            status = self.selected().load()['status']
            command = {'discovering': '/discover', 'awaiting_answers': '/answer', 'ready_to_plan': '/plan',
                       'planned': '/run', 'executing': '/run', 'interrupted': '/run'}.get(status, '/status')
        if command in {'/discover', '/plan', '/run'}:
            audit = self.selected(value)
            self.check_model(audit)
            with audit.lock():
                self.state.pop('reviewed_plan', None)
                self.state.pop('answering', None)
                if command == '/discover':
                    discover(audit, self.provider, self.config.max_prompt_bytes)
                    return self.status(audit)
                if command == '/plan':
                    plan(self.workspace, self.config, audit, self.provider)
                return self.review(audit)
        if command == '/status':  # /next after a completed run
            return self.status(self.selected())
        raise ForgeError('Unknown command. Use /help for available actions, or /ask TEXT to ask your model.')

    def context(self) -> dict:
        result = {}
        if self.state.get('request_draft'):
            result['request_draft'] = self.state['request_draft']
        if self.state.get('workflow_run'):
            audit = self.selected()
            state = audit.load()
            result['coding_run'] = {key: state.get(key) for key in ('title', 'status', 'questions', 'provider', 'model')}
            result['coding_run']['id'] = self.state['workflow_run']
            result['coding_run']['request'] = audit.read('request.md')
            for name in ('plan.md', 'summary.md'):
                if (audit.path / name).is_file():
                    result['coding_run'][name] = audit.read(name)
        return result
