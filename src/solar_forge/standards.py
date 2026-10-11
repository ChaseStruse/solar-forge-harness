"""Starter language guidance and bounded filename-based project detection."""
from importlib.resources import files
from pathlib import PurePosixPath

from .context import bundled_guidance
from .domain import ForgeError, SUPPORTED_LANGUAGES

LABELS = {'python': 'Python', 'typescript': 'TypeScript', 'javascript': 'JavaScript'}


def select_languages(values):
    """Normalize explicit selections; generic must stand alone."""
    selected = set(values)
    if not selected or selected == {'generic'}:
        return []
    if not selected <= set(SUPPORTED_LANGUAGES):
        raise ForgeError('Choose python, typescript, javascript, or generic alone.')
    return [name for name in SUPPORTED_LANGUAGES if name in selected]


def detect_languages(workspace):
    # Use the same bounded, filtered inventory as model file discovery. File
    # contents are not opened or executed to infer a project's language.
    names = workspace.inventory(limit=500)
    detected = set()
    package_json = False
    for name in names:
        path = PurePosixPath(name)
        if path.suffix.lower() in {'.py', '.pyi'} or path.name in {'pyproject.toml', 'requirements.txt', 'Pipfile'}:
            detected.add('python')
        if path.suffix.lower() in {'.ts', '.tsx', '.mts', '.cts'} or (
                path.name == 'tsconfig.json' or path.name.startswith('tsconfig.') and path.suffix == '.json'):
            detected.add('typescript')
        if path.suffix.lower() in {'.js', '.jsx', '.mjs', '.cjs'}:
            detected.add('javascript')
        package_json |= path.name == 'package.json'
    if package_json and 'typescript' not in detected:
        detected.add('javascript')
    return [name for name in SUPPORTED_LANGUAGES if name in detected]


def coding_standards(languages):
    selected = select_languages(languages)
    generic = bundled_guidance()['builtin/coding.md'].rstrip() + '\n'
    if not selected:
        return generic
    text = generic + ('\nThese are editable starter defaults. Existing project requirements and tool\n'
                      'configuration take precedence. Apply each language section only to its files.\n')
    root = files('solar_forge').joinpath('guidance')
    for name in selected:
        text += '\n' + root.joinpath(name + '.md').read_text(encoding='utf-8').rstrip() + '\n'
    return text


def language_summary(languages):
    return ', '.join(LABELS[name] for name in languages) or 'Generic'
