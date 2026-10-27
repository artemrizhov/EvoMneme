"""Small agent-facing navigation/setup CLI, separate from the SQL executor."""
import argparse
import sys

from evomneme_navigate import NavigationError, navigate, text_lines


def build_parser(parser_class=argparse.ArgumentParser):
    from evomneme_connection import configure_parser
    from evomneme_install import configure_parser as configure_install
    from evomneme_mutate import configure_parser as configure_mutations
    from evomneme_references import configure_parser as configure_references
    from evomneme_diagnostics import configure_parser as configure_diagnostics
    parser = parser_class(description='Read and maintain bound project knowledge; source code remains the truth.',
                          epilog='Chain commands with --next before --: reads share a snapshot; mutations commit atomically. '
                                 'Do not mix reads/writes or chain setup/help. -- makes the literal remainder the last segment. '
                                 'Use --summary=--next for a literal flag value. Read-chain --all anywhere removes the aggregate '
                                 '64 KiB guard; the complete chain keeps one five-second deadline.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('nodes', 'links'):
        sub = subparsers.add_parser(name, epilog='Chain read commands with --next before --; one snapshot and five-second deadline. '
                                   '-- makes the literal remainder the last segment. Any read-segment --all opts out for the entire chain.')
        sub.add_argument('names', metavar='NAME', nargs='+')
        sub.add_argument('--all', action='store_true', dest='all_output', help='Allow complete output above 64 KiB; in a read chain opts out for the entire chain; five-second deadline remains.')
    configure_parser(subparsers)
    configure_install(subparsers)
    configure_mutations(subparsers)
    configure_references(subparsers)
    configure_diagnostics(subparsers)
    return parser


def main(argv=None):
    from evomneme_connection import discover
    from evomneme_mutate import run as run_mutation
    from evomneme_references import run as run_references
    from evomneme_chain import ChainParser, parse_segments, run as run_chain, split_segments
    try:
        segments = split_segments(list(sys.argv[1:] if argv is None else argv))
        if len(segments) > 1:
            parsed, category = parse_segments(build_parser(ChainParser), segments)
            output = run_chain(discover(), parsed, category, segments)
        else:
            args = build_parser().parse_args(segments[0])
            if hasattr(args, 'setup_handler'):
                return args.setup_handler(args)
            if args.command == 'links' and len(args.names) > 2:
                raise NavigationError('links accepts one or two node names.')
            connection = discover()
            if getattr(args, 'diagnostic', False):
                from evomneme_diagnostics import run as run_diagnostic
                output = run_diagnostic(connection, args)
            elif getattr(args, 'references', False):
                output = run_references(connection, args)
            elif getattr(args, 'mutation', False):
                output = run_mutation(connection, args)
            else:
                output = navigate(connection, args.command, args.names, all_output=args.all_output)
        # Match the UTF-8 byte guard even with Windows newline/locale defaults.
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout.buffer.write(output.encode('utf-8'))
        else:
            sys.stdout.write(output)
        return 0
    except (ValueError, OSError) as exc:
        first, *rest = text_lines(exc)
        print('evomneme: ' + first + ''.join('\n  ' + line for line in rest), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
