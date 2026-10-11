"""Best-effort activity snapshots derived from audit events, never workflow state."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import math

from .workspace import atomic_write

_OBSERVER = ContextVar('forge_progress_observer', default=None)
MAX_FILES = 500


def with_progress(callback, function, *args, **kwargs):
    token = _OBSERVER.set(callback)
    try:
        return function(*args, **kwargs)
    finally:
        _OBSERVER.reset(token)


def read_progress(audit):
    path = audit.path / 'progress.json'
    try:
        if not path.exists() or path.is_symlink() or path.stat().st_size > 200000:
            return None
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or data.get('version') != 1:
            return None
        if (not all(isinstance(data[key], str) for key in ('scope', 'action', 'updated_at'))
                or not isinstance(data['changed_files'], list)
                or not all(isinstance(name, str) for name in data['changed_files'])
                or len(data['changed_files']) > MAX_FILES
                or type(data['active_seconds']) not in (int, float)
                or not math.isfinite(data['active_seconds']) or data['active_seconds'] < 0
                or type(data['files_overflow']) is not bool or type(data['history_limited']) is not bool):
            return None
        for key in ('calls', 'input_tokens', 'output_tokens', 'input_reports', 'output_reports'):
            if type(data['usage'][key]) is not int or data['usage'][key] < 0:
                return None
        if data['active_since'] is not None:
            seconds(data['active_since'], data['updated_at'])
        check = data['latest_check']
        if check is not None and (not isinstance(check, dict)
                or not isinstance(check.get('name'), str) or not isinstance(check.get('status'), str)):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return None


def seconds(start, end):
    return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def action_label(action):
    labels = {'list_files': 'Listing project files', 'read_file': 'Reading', 'write_file': 'Writing',
              'run_check': 'Running check', 'search_docs': 'Searching reference documents',
              'ask_questions': 'Recording questions', 'finish': 'Preparing review'}
    tool = action.get('tool')
    label = labels.get(tool, 'Validating model action')
    if tool in {'read_file', 'write_file', 'run_check'}:
        value = action.get('path' if tool != 'run_check' else 'name')
        if isinstance(value, str):
            label += ': ' + value[:160]
    return label


FINAL_LABELS = {'questions_generated': 'Discovery complete', 'plan_generated': 'Plan ready for review',
                'review_requested': 'Review required', 'execution_questions_generated': 'Awaiting answers',
                'turn_limit_reached': 'Turn limit reached', 'execution_interrupted': 'Interrupted',
                'chat_reply_recorded': 'Reply saved', 'chat_reply_failed': 'Reply failed'}
EVENTS = {'created', 'chat_created', 'provider_call_started', 'provider_call_finished', 'provider_call_failed',
          'tool_attempted', 'tool_result', 'tool_rejected', 'action_rejected', 'file_written',
          'verification_started', 'verification_finished', 'execution_started'} | set(FINAL_LABELS)


def update_progress(audit, event):
    kind, at = event['type'], event['at']
    if kind not in EVENTS:
        return
    data = read_progress(audit) or {
        'version': 1, 'scope': 'Run', 'tracking_since': at, 'updated_at': at,
        'history_limited': kind != 'created', 'action': 'Ready', 'active_since': None,
        'active_seconds': 0, 'changed_files': [], 'files_overflow': False, 'latest_check': None,
        'turn': 0, 'usage': {'calls': 0, 'input_tokens': 0, 'output_tokens': 0,
                             'input_reports': 0, 'output_reports': 0}}

    def stop():
        if data['active_since']:
            data['active_seconds'] += seconds(data['active_since'], at)
            data['active_since'] = None

    def start(label):
        data['action'] = label
        if not data['active_since']:
            data['active_since'] = at

    if kind == 'chat_created':
        data['scope'] = 'Chat'
    elif kind == 'execution_started':
        # A previous hard interruption has no reliable end timestamp. Never
        # count time spent away from Forge as active work.
        if data['active_since']:
            data['active_seconds'] += seconds(data['active_since'], data['updated_at'])
            data['active_since'] = None
            data['history_limited'] = True
        data['action'] = 'Starting coding'
    elif kind == 'provider_call_started':
        if data['active_since']:
            data['active_seconds'] += seconds(data['active_since'], data['updated_at'])
            data['history_limited'] = True
        data['active_since'] = at
        data['action'] = 'Waiting for model'
        data['usage']['calls'] += 1
    elif kind in {'provider_call_finished', 'provider_call_failed'}:
        stop()
        data['action'] = 'Model reply received' if kind.endswith('finished') else 'Model call failed'
        usage = event.get('usage') or {}
        for field in ('input', 'output'):
            value = usage.get(field + '_tokens')
            if type(value) is int and value >= 0:
                data['usage'][field + '_tokens'] += value
                data['usage'][field + '_reports'] += 1
    elif kind == 'tool_attempted':
        data['turn'] = event.get('turn', data['turn'])
        start(action_label(event.get('action', {})))
    elif kind == 'file_written' and event.get('changed', True):
        name = event['path']
        if name not in data['changed_files']:
            if len(data['changed_files']) < MAX_FILES:
                data['changed_files'].append(name)
            else:
                data['files_overflow'] = True
        if data['latest_check']:
            data['latest_check']['stale'] = True
    elif kind == 'verification_started':
        start('Running check: ' + event['name'][:160])
    elif kind == 'verification_finished':
        data['latest_check'] = {key: event.get(key) for key in ('name', 'status', 'exit_code')}
        data['latest_check']['stale'] = False
    elif kind == 'tool_result':
        stop()
        result = event.get('result', {})
        if 'name' in result and 'exit_code' in result and 'status' in result:
            data['latest_check'] = {key: result.get(key) for key in ('name', 'status', 'exit_code')}
            data['latest_check']['stale'] = False
        # Preserve the final workflow status emitted from inside an action.
        if data['action'] not in FINAL_LABELS.values():
            data['action'] = 'Action complete'
    elif kind in {'tool_rejected', 'action_rejected'}:
        stop()
        data['action'] = 'Action rejected; awaiting next step'
    elif kind in FINAL_LABELS:
        stop()
        data['action'] = FINAL_LABELS[kind]
    data['updated_at'] = at
    data['audit_path'] = '/'.join(audit.path.parts[-3:])
    atomic_write(audit.path / 'progress.json', json.dumps(data, ensure_ascii=False))
    observer = _OBSERVER.get()
    if observer:
        try:
            observer(data)
        except Exception:
            pass  # A display failure must never interrupt an approved action.


def format_progress(data, *, live=False, width=100, stop_requested=False, now=None):
    if not data:
        return 'Activity unavailable for this saved run.'
    elapsed = data['active_seconds']
    if data['active_since']:
        end = (now or datetime.now(timezone.utc).isoformat()) if live else data['updated_at']
        elapsed += seconds(data['active_since'], end)
    minutes, sec = divmod(int(elapsed), 60)
    action = 'Stop requested; waiting for a safe boundary' if stop_requested else data['action']
    if data['active_since'] and not live:
        action = 'Last recorded: ' + action
    files = data['changed_files']
    file_text = ', '.join(files[-2:]) or 'none'
    check = data['latest_check']
    check_text = ('none yet' if not check else f"{check['name']}: {check['status']}"
                  + (f" (exit {check['exit_code']})" if check.get('exit_code') is not None else '')
                  + ('; rerun after edits' if check.get('stale') else ''))
    usage = data['usage']
    counts = []
    for field in ('input', 'output'):
        reports = usage[field + '_reports']
        counts.append(f"{usage[field + '_tokens']:,}" if reports else 'unavailable')
    partial = any(usage[field + '_reports'] < usage['calls'] for field in ('input', 'output'))
    tokens = f'Tokens: {counts[0]} in / {counts[1]} out'
    if partial and any(usage[field + '_reports'] for field in ('input', 'output')):
        tokens += ' (partial)'
    lines = [f"{data['scope']} · {minutes:02}:{sec:02} active · {action}",
             f"Changed ({len(files)}{'+' if data['files_overflow'] else ''}): {file_text}",
             'Check: ' + check_text, tokens]
    if data['history_limited']:
        lines[-1] += '; earlier activity unavailable'
    return '\n'.join(line if len(line) <= width else line[:max(0, width-1)] + '…' for line in lines)
