"""Bounded tool loop with approval, write journaling, and recovery."""
import difflib
import hashlib
import json

from .audit import Audit, now
from .domain import Config, ForgeError
from .providers import Provider
from .workflow import SYSTEM, assert_current, call, parse_json, payload, plan_digest, questions_from
from .workspace import Workspace

TOOLS = """
Execute the approved plan one action at a time. Return one JSON object:
{"tool":"list_files"}
{"tool":"read_file","path":"project-relative/file"}
{"tool":"write_file","path":"project-relative/file","content":"full UTF-8 content"}
{"tool":"ask_questions","questions":[{"question":"specific unresolved decision",
 "rationale":"why this matters","sources":["request.md or supplied documents key"]}]}
{"tool":"finish","summary":"changes and remaining work","verification":"suggested checks"}
Read an existing file before writing it. Do not alter project policies or the
request. There is no command runner, deletion, Git, or deployment tool. If a new
consequential decision is unclear, ask_questions before making further changes.
Tool results are returned as user messages. finish creates a human review record;
it cannot verify acceptance criteria or prove tests have passed.
"""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def approve(audit: Audit) -> None:
    state = audit.load()
    if state['status'] != 'planned':
        raise ForgeError('Generate a plan before approving execution.')
    state['approved_plan'] = plan_digest(audit)
    state['approved_at'] = now()
    audit.save(state)
    audit.event('plan_approved', sha256=state['approved_plan'])


def validate_action(action: dict) -> str:
    tool = action.get('tool')
    shapes = {'list_files': set(), 'read_file': {'path'}, 'write_file': {'path', 'content'},
              'ask_questions': {'questions'}, 'finish': {'summary', 'verification'}}
    if not isinstance(tool, str) or tool not in shapes:
        raise ForgeError('Unknown tool. Use list_files, read_file, write_file, ask_questions, or finish.')
    if set(action) != shapes[tool] | {'tool'}:
        raise ForgeError(f'Unexpected or missing arguments for {tool}.')
    for name in shapes[tool] - {'questions'}:
        if not isinstance(action[name], str):
            raise ForgeError(f'{name} must be a string.')
    return tool


def write_file(workspace: Workspace, config: Config, audit: Audit, state: dict, action: dict) -> dict:
    assert_current(workspace, config, audit)
    relative, content = action['path'], action['content']
    target = workspace.path(relative, write=True)
    protected = {workspace.path(p) for p in config.docs} | {workspace.path(state['request_path'])}
    if target in protected:
        raise ForgeError('Request and context documentation cannot be edited during this run.')
    if len(content.encode()) > workspace.max_file_bytes:
        raise ForgeError('Write exceeds configured file size limit.')
    change_id = f"changes/{state['turns']:04d}"
    journal = audit.path / change_id / 'metadata.json'
    if journal.exists():
        meta = json.loads(journal.read_text())
        before = audit.read(change_id + '/before.txt')
    else:
        existed = target.exists()
        before = workspace.read(relative) if existed else ''
        before_hash = digest(before) if existed else None
        versions = state.get('read_versions', {})
        if existed and (relative not in versions or versions[relative] != before_hash):
            raise ForgeError('Read the current file before writing; it changed or was not read.')
        meta = {'path': relative, 'existed': existed, 'before_sha256': before_hash,
                'after_sha256': digest(content)}
        audit.write(change_id + '/before.txt', before)
        audit.write(change_id + '/after.txt', content)
        diff = ''.join(difflib.unified_diff(before.splitlines(keepends=True), content.splitlines(keepends=True),
                                          fromfile=relative + ' (before)', tofile=relative + ' (after)'))
        audit.write(change_id + '/diff.patch', diff)
        audit.write(change_id + '/metadata.json', json.dumps(meta, indent=2))
        audit.event('write_intent', **meta, evidence=change_id)
    current = workspace.read(relative) if target.exists() else None
    current_hash = digest(current) if current is not None else None
    if current_hash == meta['after_sha256']:
        result = {'path': relative, 'sha256': meta['after_sha256'], 'recovered': True}
    elif current_hash == meta['before_sha256']:
        workspace.write(relative, content)
        result = {'path': relative, 'sha256': meta['after_sha256'], 'recovered': False}
    else:
        raise ForgeError('File changed after write intent; inspect the audit diff before proceeding.')
    state.setdefault('read_versions', {})[relative] = meta['after_sha256']
    audit.event('file_written', **result, evidence=change_id)
    return result


def execute(workspace: Workspace, config: Config, audit: Audit, state: dict, action: dict) -> dict:
    tool = validate_action(action)
    if tool == 'list_files':
        return {'files': workspace.inventory(), 'limit': 500}
    if tool == 'read_file':
        content = workspace.read(action['path'])
        state.setdefault('read_versions', {})[action['path']] = digest(content)
        return {'path': action['path'], 'content': content, 'sha256': digest(content)}
    if tool == 'write_file':
        return write_file(workspace, config, audit, state, action)
    if tool == 'ask_questions':
        context = payload(audit, state)['context']
        questions = questions_from(action, set(context['documents']) | {'request.md'}, len(state['questions']) + 1)
        if not questions:
            raise ForgeError('ask_questions requires at least one question.')
        state['questions'].extend(questions)
        state.update({'status': 'awaiting_answers', 'approved_plan': None})
        audit.questions(state)
        audit.event('execution_questions_generated', count=len(questions))
        return {'paused': True, 'reason': 'Answer questions and generate a revised plan before further edits.'}
    if not action['summary'].strip() or not action['verification'].strip():
        raise ForgeError('finish needs nonempty summary and verification strings.')
    audit.write('summary.md', '# Review required\n\n' + action['summary'] + '\n\n'
                '## Suggested verification (not executed)\n\n' + action['verification'] + '\n\n'
                'The harness has no command runner. Acceptance criteria and tests remain unverified.\n')
    state['status'] = 'review_required'
    audit.event('review_requested')
    return {'status': 'review_required', 'acceptance_criteria_verified': False}


def run(workspace: Workspace, config: Config, audit: Audit, provider: Provider) -> None:
    state = audit.load()
    if state['status'] not in {'planned', 'executing', 'interrupted', 'turn_limit'}:
        raise ForgeError('This run needs answered questions and an approved plan before execution.')
    assert_current(workspace, config, audit)
    if not state.get('approved_plan') or state['approved_plan'] != plan_digest(audit):
        raise ForgeError('The current plan has not been approved.')
    state['status'] = 'executing'
    audit.save(state)
    content = payload(audit, state)
    content['approved_plan'] = (audit.path / 'plan.md').read_text()
    system = SYSTEM + TOOLS + '\nRun context:\n' + json.dumps(content)
    if not state['messages']:
        state['messages'] = [{'role': 'user', 'content': 'Begin the approved plan. Inspect relevant files first.'}]
    try:
        while state['turns'] < config.max_turns or state.get('pending_action'):
            if not state.get('pending_action'):
                state['turns'] += 1
                audit.save(state)
                text = call(audit, provider, system, state['messages'], config.max_prompt_bytes)
                state['messages'].append({'role': 'assistant', 'content': text})
                try:
                    action = parse_json(text)
                except ForgeError as exc:
                    audit.event('action_rejected', error=str(exc), turn=state['turns'])
                    state['messages'].append({'role': 'user', 'content': json.dumps({'error': str(exc)})})
                    audit.save(state)
                    continue
                state['pending_action'] = action
                audit.save(state)
                audit.event('tool_attempted', turn=state['turns'], action=action)
            action = state['pending_action']
            try:
                result = execute(workspace, config, audit, state, action)
                audit.event('tool_result', turn=state['turns'], result=result)
            except (ForgeError, OSError) as exc:
                result = {'error': str(exc)}
                audit.event('tool_rejected', turn=state['turns'], error=str(exc))
            state['messages'].append({'role': 'user', 'content': json.dumps(result)})
            state.pop('pending_action', None)
            audit.save(state)
            if state['status'] != 'executing':
                return
        state['status'] = 'turn_limit'
        audit.save(state)
        audit.event('turn_limit_reached', turns=state['turns'])
    except (Exception, KeyboardInterrupt):
        state['status'] = 'interrupted'
        audit.save(state)
        audit.event('execution_interrupted', turns=state['turns'])
        raise
