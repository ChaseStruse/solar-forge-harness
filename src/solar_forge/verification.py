"""Opt-in trusted verification commands; this is not an OS sandbox."""
import json
import os
import selectors
import signal
import subprocess
import time

from .domain import ForgeError


def run_check(workspace, config, audit, state, name, *, cancelled=None):
    policy = config.verification.snapshot()
    if name not in policy['commands']:
        raise ForgeError('Unknown verification command; configure a named check before preparing a run.')
    if os.name != 'posix':
        raise ForgeError('Controlled verification currently requires POSIX process groups.')
    folder = f"verification/{state['turns']:04d}"
    result_path = audit.path / folder / 'result.json'
    if result_path.exists():
        return json.loads(result_path.read_text())
    intent_path = audit.path / folder / 'intent.json'
    if intent_path.exists():
        # Execution may have happened before a crash. Never replay side effects.
        result = json.loads(intent_path.read_text()) | {
            'status': 'interrupted', 'exit_code': None, 'output': '',
            'truncated': False, 'duration_seconds': None,
            'note': 'Outcome unknown after interruption; request a new check action to rerun.'}
        audit.write(folder + '/result.json', json.dumps(result, indent=2))
        return result
    intent = {'name': name, 'argv': policy['commands'][name], 'cwd': str(workspace.root),
              'timeout': policy['timeout'], 'max_output_bytes': policy['max_output_bytes'],
              'turn': state['turns'], 'evidence': folder + '/result.json'}
    audit.write(folder + '/intent.json', json.dumps(intent, indent=2))
    audit.event('verification_started', **intent)
    started = time.monotonic()
    output = bytearray()
    truncated = False
    status = 'passed'
    process = None
    exit_code = None
    try:
        if cancelled and cancelled():
            status = 'cancelled'
        else:
            # Do not inherit provider credentials or arbitrary ambient variables.
            env = {'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C.UTF-8'} | policy['env']
            process = subprocess.Popen(intent['argv'], cwd=workspace.root, env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True,
                                       shell=False)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map() or process.poll() is None:
                    if cancelled and cancelled():
                        status = 'cancelled'
                        break
                    if time.monotonic() - started >= policy['timeout']:
                        status = 'timed_out'
                        break
                    for key, _ in selector.select(timeout=0.05):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        available = policy['max_output_bytes'] - len(output)
                        output.extend(chunk[:available])
                        truncated |= len(chunk) > available
            if status == 'passed':
                exit_code = process.wait()
                status = 'passed' if exit_code == 0 else 'failed'
    except OSError as exc:
        status = 'error'
        output = bytearray(str(exc).encode()[:policy['max_output_bytes']])
    finally:
        if process is not None:
            # Kill descendants as well, even if the direct child has already exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            exit_code = process.returncode
            process.stdout.close()
    result = intent | {'status': status, 'exit_code': exit_code,
                       'output': output.decode('utf-8', errors='replace'), 'truncated': truncated,
                       'duration_seconds': round(time.monotonic() - started, 3)}
    audit.write(folder + '/result.json', json.dumps(result, indent=2))
    audit.event('verification_finished', name=name, status=status, exit_code=exit_code, evidence=result['evidence'])
    return result


def review_checks(state):
    checks = state.get('verification_results', [])
    if not checks:
        return 'No verification commands were executed. Acceptance criteria and tests remain unverified.\n'
    lines = ['## Recorded verification\n']
    for result in checks:
        stale = result['turn'] < state.get('last_write_turn', 0)
        lines.append(f"- {result['name']}: {result['status']}"
                     + (' (predates later edits; rerun needed)' if stale else '')
                     + f" — evidence: {result['evidence']}")
    lines.append('\nThese are command outcomes, not certification of all acceptance criteria. '
                 'Commands can modify the workspace; human review remains required.\n')
    return '\n'.join(lines)
