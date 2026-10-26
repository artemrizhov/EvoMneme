"""Install only this tool's launcher using the already running Python runtime."""
import os
import base64
from pathlib import Path
import shlex
import sys


class InstallError(ValueError):
    pass


def configure_parser(subparsers):
    parser = subparsers.add_parser('install', help='Create a launcher without installing a runtime or changing profiles')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--bin-dir', type=Path, help='Existing writable directory already in PATH')
    group.add_argument('--activate', type=Path, help='Project-local directory for an explicitly sourced session activation')
    parser.set_defaults(setup_handler=run_setup)


def _ps_quote(value):
    return "'" + value.replace("'", "''") + "'"


def launcher_text(python, cli, windows=None):
    windows = os.name == 'nt' if windows is None else windows
    if windows:
        bootstrap = ('import sys,json,base64,runpy,os;'
                     'sys.stdout.reconfigure(encoding="utf-8");sys.stderr.reconfigure(encoding="utf-8");'
                     'sys.argv=json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"));'
                     'sys.path.insert(0,os.path.dirname(sys.argv[0]));'
                     'runpy.run_path(sys.argv[0],run_name="__main__")')
        encoded = base64.b64encode(bootstrap.encode('utf-8')).decode('ascii')
        code = "exec(__import__('base64').b64decode('" + encoded + "'))"
        # PowerShell owns the string arguments. Only ASCII base64 crosses its
        # legacy native-process argument serializer; cmd.exe never parses names.
        return ('# EvoMneme launcher: execution policy is respected.\n'
                '$evomnemeArgv = @(' + _ps_quote(str(cli)) + ') + @($args | ForEach-Object { [string]$_ })\n'
                '$evomnemeJson = ConvertTo-Json -InputObject $evomnemeArgv -Compress\n'
                '$evomnemeEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($evomnemeJson))\n'
                '$evomnemePreviousEncoding = [Console]::OutputEncoding\n'
                'try {\n'
                '  [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)\n'
                '  & ' + _ps_quote(str(python)) + ' -c "' + code + '" $evomnemeEncoded\n'
                '  $evomnemeExitCode = $LASTEXITCODE\n'
                '} finally { [Console]::OutputEncoding = $evomnemePreviousEncoding }\n'
                'exit $evomnemeExitCode\n')
    return '#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' ' + shlex.quote(str(cli)) + ' "$@"\n'


def run_setup(args) -> int:
    target = (args.bin_dir or args.activate).resolve()
    if args.bin_dir:
        members = {Path(part).resolve() for part in os.environ.get('PATH', '').split(os.pathsep) if part}
        if not target.is_dir() or target not in members:
            raise InstallError('--bin-dir must be an existing directory already in PATH; use --activate for session activation')
    else:
        # Activation is a project file, never a hidden user-profile edit.
        project = Path.cwd().resolve()
        for parent in (project, *project.parents):
            if (parent / '.git').exists() or (parent / '.evomneme/connection.json').exists():
                project = parent
                break
        if not target.is_relative_to(project) or target == project:
            raise InstallError('--activate must name a directory inside the current project')
    outputs = [target / ('evomneme.ps1' if os.name == 'nt' else 'evomneme')]
    if args.activate:
        outputs.extend([target / 'activate.ps1', target / 'activate.sh'])
    # Refuse all command-name collisions, including commands from other tools.
    for name in ('evomneme', 'evomneme.cmd', 'evomneme.exe', 'evomneme.bat', 'evomneme.ps1'):
        if (target / name).exists():
            raise InstallError('Refusing to replace existing command: ' + str(target / name))
    if any(path.exists() for path in outputs):
        raise InstallError('Activation file already exists; refusing to overwrite it')
    python = Path(sys.executable).resolve()
    cli = Path(__file__).resolve().with_name('evomneme_cli.py')
    if not python.is_file() or not cli.is_file():
        raise InstallError('Selected Python or live navigation CLI is missing')
    if args.activate:
        target.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        with outputs[0].open('x', encoding='utf-8-sig' if os.name == 'nt' else 'utf-8', newline='\n') as stream:
            stream.write(launcher_text(python, cli))
        written.append(outputs[0])
        if os.name != 'nt':
            outputs[0].chmod(outputs[0].stat().st_mode | 0o111)
        if args.activate:
            texts = ["$env:PATH = " + _ps_quote(str(target) + os.pathsep) + " + $env:PATH\n",
                     'export PATH=' + shlex.quote(str(target)) + ':"$PATH"\n']
            for path, content in zip(outputs[1:], texts):
                with path.open('x', encoding='utf-8-sig' if path.suffix == '.ps1' else 'utf-8', newline='\n') as stream:
                    stream.write(content)
                written.append(path)
    except OSError as exc:
        for path in written:
            path.unlink()
        raise InstallError('Cannot write launcher directory: ' + str(exc)) from exc
    print('Launcher created: ' + str(outputs[0]))
    if args.activate:
        print('Activate in this PowerShell session: . ' + _ps_quote(str(target / 'activate.ps1')))
        print('Activate in this POSIX shell session: . ' + shlex.quote(str(target / 'activate.sh')))
    return 0
