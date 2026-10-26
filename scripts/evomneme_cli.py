"""Small agent-facing navigation/setup CLI, separate from the SQL executor."""
import argparse
import sys

from evomneme_navigate import NavigationError, navigate


def main(argv=None):
    from evomneme_connection import configure_parser, discover
    from evomneme_install import configure_parser as configure_install
    parser = argparse.ArgumentParser(description='Read bound project knowledge; source code remains the truth.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('nodes', 'links'):
        sub = subparsers.add_parser(name)
        sub.add_argument('names', metavar='NAME', nargs='+')
        sub.add_argument('--all', action='store_true', dest='all_output', help='Allow complete output above 64 KiB; pipe or save if needed.')
    configure_parser(subparsers)
    configure_install(subparsers)
    args = parser.parse_args(argv)
    try:
        if hasattr(args, 'setup_handler'):
            return args.setup_handler(args)
        if args.command == 'links' and len(args.names) > 2:
            raise NavigationError('links accepts one or two node names.')
        output = navigate(discover(), args.command, args.names, all_output=args.all_output)
        # Match the UTF-8 byte guard even with Windows newline/locale defaults.
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout.buffer.write(output.encode('utf-8'))
        else:
            sys.stdout.write(output)
        return 0
    except (ValueError, OSError) as exc:
        print('evomneme: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
