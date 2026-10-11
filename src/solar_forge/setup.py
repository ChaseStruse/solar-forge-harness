"""Guided project setup with no model calls or stored credentials."""
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import tomllib

from .context import bundled_guidance
from .domain import Config, CONFIG_TEMPLATE, ForgeError, RagConfig, REQUEST_TEMPLATE
from .requests import DEFAULT_REQUEST
from .providers import validate_base_url
from .workspace import EXCLUDED, Workspace
from .standards import coding_standards, detect_languages, select_languages, language_summary

PROVIDERS = (
    ('ollama', 'Ollama — a model running on your computer', 'http://localhost:11434', ''),
    ('openai', 'OpenAI — requires an API key', 'https://api.openai.com/v1', 'OPENAI_API_KEY'),
    ('anthropic', 'Claude (Anthropic) — requires an API key', 'https://api.anthropic.com/v1', 'ANTHROPIC_API_KEY'),
    ('compatible', 'OpenAI-compatible server — local or hosted', 'http://localhost:8080/v1', 'LOCAL_MODEL_API_KEY'),
)


def create(workspace: Workspace, name: str, content: str, *, internal=False) -> bool:
    path = workspace.path(name, write=True, internal=internal)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as handle:
            handle.write(content)
        print(f'Created {name}')
        return True
    except FileExistsError:
        if not path.is_file():
            raise ForgeError(f'Expected a file at {name}. Move the folder and try again.')
        print(f'Kept existing {name}')
        return False


def ask(label: str, default: str = '') -> str:
    while True:
        value = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip()
        if value or default:
            return value or default
        print('Please enter a value.')


def choice(label: str, options: tuple[str, ...], default: str) -> str:
    while True:
        value = ask(label, default).lower()
        if value in options:
            return value
        print('Choose ' + ', '.join(options) + '.')


def folder(workspace: Workspace, value: str, *, rag=False, existing=False) -> str:
    """Accept absolute paths inside the project, but preserve symlink checks."""
    path = Path(os.path.expanduser(value))
    if path.is_absolute():
        try:
            path = path.relative_to(workspace.root)
        except ValueError as exc:
            raise ForgeError('Choose a folder inside this project. Copy outside documents into the project first.') from exc
    relative = path.as_posix()
    internal = rag and (relative == '.forge/rag' or relative.startswith('.forge/rag/'))
    target = workspace.path(relative, write=True, internal=internal)
    if not internal and any(part in EXCLUDED for part in path.parts):
        raise ForgeError('Choose a project folder outside hidden Forge files, build folders, and dependencies.')
    if target.exists() and not target.is_dir():
        raise ForgeError('That path is a file. Choose a folder instead.')
    for parent in target.parents:
        if parent == workspace.root:
            break
        if parent.exists() and not parent.is_dir():
            raise ForgeError('Part of that path is a file. Choose a folder instead.')
    if existing and not target.is_dir():
        raise ForgeError('That folder does not exist. Enter the path to an existing folder.')
    return relative


def ask_folder(workspace: Workspace, label: str, default='', **kwargs) -> str:
    while True:
        try:
            return folder(workspace, ask(label, default), **kwargs)
        except ForgeError as exc:
            print(exc)


def render_config(config: Config) -> str:
    # JSON strings/arrays also use valid TOML escaping, including quotes in paths.
    values = {name: getattr(config, name) for name in
              ('kind', 'model', 'base_url', 'api_key_env', 'docs', 'languages')}
    text = CONFIG_TEMPLATE
    for name, value in values.items():
        text = re.sub(rf'(?m)^(?:# )?{name} = .*$', lambda _: f'{name} = {json.dumps(value, ensure_ascii=False)}', text)
    text = text.replace('storage = "deferred" # deferred | local', f'storage = "{config.rag.storage}"')
    text = text.replace('path = ""', f'path = {json.dumps(config.rag.path, ensure_ascii=False)}')
    return text


def choose_languages(workspace: Workspace) -> list[str]:
    detected = detect_languages(workspace)
    default = ', '.join(detected) or 'generic'
    print('Detected from up to 500 project paths: ' + language_summary(detected))
    print('Choose python, typescript, javascript, or generic. Separate multiple languages with commas.')
    while True:
        value = ask('Coding standards', default).lower()
        try:
            return select_languages(value.replace(',', ' ').split())
        except ForgeError as exc:
            print(exc)


def guided_config(workspace: Workspace, languages: list[str] | None = None) -> Config:
    print('\n1 of 4: Choose your model service')
    for number, (_, label, _, _) in enumerate(PROVIDERS, 1):
        print(f'  {number}. {label}')
    selected = choice('Choose a number', ('1', '2', '3', '4'), '1')
    kind, _, base_url, key_env = PROVIDERS[int(selected) - 1]
    print('Use the model name from your service or your installed local models.')
    while True:
        model = ask('Model name')
        if model != 'CHANGE_ME':
            break
        print('Enter your actual model name so you can start chatting.')
    base_url = ask('Service address (press Enter to keep the usual address)', base_url)
    # Reuse endpoint validation without checking credentials or contacting a service.
    while True:
        try:
            validate_base_url(base_url)
            break
        except ForgeError as exc:
            print(exc)
            base_url = ask('Service address', PROVIDERS[int(selected) - 1][2])
    if key_env:
        print('Forge reads your API key from an environment variable. Do not paste the key here.')
        while True:
            key_env = ask('API key variable name', key_env)
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key_env):
                break
            print('Use a variable name such as MY_API_KEY (letters, numbers, and underscores).')

    print('\n2 of 4: Project documents')
    print('Forge reads Markdown, text, and reStructuredText files in this folder, including subfolders.')
    print('These documents are included in messages sent to your chosen model service.')
    exists = choice('Do you already have a documents folder? (yes/no)', ('yes', 'y', 'no', 'n'), 'no')
    docs_folder = (ask_folder(workspace, 'Documents folder path (inside this project)', existing=True)
                   if exists in {'yes', 'y'} else folder(workspace, 'docs'))
    if exists in {'no', 'n'}:
        print('We will use docs/ at the project root, creating it if needed.')

    print('\n3 of 4: Document search storage (RAG)')
    print('RAG finds relevant passages from local documents for your model, with source citations.')
    print('After setup, run forge index (or /index in chat) to build the document library.')
    print('  1. Enable local document search\n  2. Set up later')
    storage = choice('Choose a number', ('1', '2'), '2')
    rag = RagConfig()
    if storage == '1':
        rag = RagConfig('local', ask_folder(workspace, 'Storage folder path', '.forge/rag', rag=True))
    print('\n4 of 4: Language coding standards')
    languages = choose_languages(workspace) if languages is None else languages
    print('Starter templates: ' + language_summary(languages))
    docs = tomllib.loads(CONFIG_TEMPLATE)['harness']['docs']
    return replace(Config(), kind=kind, model=model, base_url=base_url, api_key_env=key_env,
                   docs=[*docs, docs_folder], rag=rag, languages=languages)


def initialize(workspace: Workspace, *, interactive: bool, languages: list[str] | None = None) -> None:
    selected = select_languages(languages) if languages is not None else None
    config_path = workspace.path('.forge/config.toml', write=True, internal=True)
    existing = config_path.exists()
    print(f'Set up Forge for {workspace.root}')
    print('Existing files will be kept. Press Ctrl-C to stop setup.')
    if existing:
        config = Config.load(config_path)
        if selected is not None and set(selected) != set(config.languages):
            raise ForgeError('Existing configuration has different harness.languages. Edit that setting explicitly; '
                             'init preserves existing coding.md. Remove coding.md only if you intend to regenerate it.')
        print('Your configuration already exists. Keeping your model, documents, and storage settings.')
    elif interactive:
        config = guided_config(workspace, selected)
    else:
        config = Config(docs=[*tomllib.loads(CONFIG_TEMPLATE)['harness']['docs'], 'docs'],
                        languages=detect_languages(workspace) if selected is None else selected)
        folder(workspace, 'docs')
        print('Prompts skipped. Edit .forge/config.toml to choose your model before chatting.')

    # Gather choices before writing so cancelling a prompt leaves no setup files.
    print('\nSetup files:')
    create(workspace, '.forge/config.toml', render_config(config), internal=True)
    created_config = not existing
    if created_config:
        docs_folder = config.docs[-1]
        target = workspace.path(docs_folder, write=True)
        existed = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        print(f'{"Kept existing" if existed else "Created"} documents folder: {docs_folder}/')
        if config.rag.storage == 'local':
            name = folder(workspace, config.rag.path, rag=True)
            target = workspace.path(name, write=True, internal=name.startswith('.forge/rag'))
            existed = target.exists()
            target.mkdir(parents=True, exist_ok=True)
            print(f'{"Kept existing" if existed else "Created"} search storage folder: {name}/')
    create(workspace, DEFAULT_REQUEST, REQUEST_TEMPLATE, internal=True)
    for name, text in bundled_guidance().items():
        if name == 'builtin/coding.md':
            text = coding_standards(config.languages)
        create(workspace, '.forge/standards/' + name.split('/')[-1], text, internal=True)

    print('\nSetup complete.')
    print(f'Project: {workspace.root}')
    print(f'Model service: {config.kind}; model: {config.model}')
    print('Settings: .forge/config.toml')
    print('Project guidance: .forge/standards/')
    print('Starter coding standards: ' + language_summary(config.languages))
    print('Edit .forge/standards/coding.md to customize; existing guidance is never replaced.')
    print('Documents: ' + (config.docs[-1] + '/' if created_config else ', '.join(config.docs)))
    print('Document search: ' + (f'local folder {config.rag.path} enabled; run forge index to build or refresh' if config.rag.storage == 'local'
                                else 'set up later (not active)'))
    if config.model == 'CHANGE_ME' or not config.model.strip():
        print('\nBefore chatting: set provider.model in .forge/config.toml to your model name.')
    if config.kind == 'ollama':
        print('Before chatting: make sure Ollama is running and your chosen model is installed.')
    elif config.api_key_env or config.kind in {'openai', 'anthropic', 'compatible'}:
        key_env = config.api_key_env or next(p[3] for p in PROVIDERS if p[0] == config.kind)
        if not os.environ.get(key_env):
            print(f'Before chatting: set the {key_env} environment variable to your API key'
                  + (' if your server requires one.' if config.kind == 'compatible' else '.'))
            print(f'  In a Bash terminal: export {key_env}="your-api-key"')
            print('  Replace your-api-key with the key from your model service. Then run forge chat in that terminal.')
    print('\nCreate your first request and chat:')
    print('  1. From the project folder, run: forge chat')
    print('  2. Type /request. Forge helps you write a request, one question at a time.')
    print('     Type /save-request when you are happy with the draft.')
    print('  3. Type /prepare, answer any questions with /answer, then type /plan.')
    print('     Read the plan. Type /approve when you want Forge to start coding.')
    print('Use /ask followed by your question for model advice at any step. /help lists all actions.')
    print('Press Enter to send. Press Ctrl-Q to leave chat. Your request and progress are saved.')
