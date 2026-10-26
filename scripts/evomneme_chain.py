"""Prevalidated homogeneous CLI chains over one snapshot or write transaction."""
import argparse
import sqlite3

from evomneme_context import ReadContext
from evomneme_mutate import MutationSession, run as mutate
from evomneme_navigate import fields, navigate, quote_command
from evomneme_references import references

OUTPUT_BYTES = 65536
TIMEOUT_SECONDS = 5.0


class ChainParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def split_segments(argv):
    """A literal -- ends separator recognition for the entire remainder."""
    segments = [[]]
    literal = False
    for token in argv:
        if token == '--' and not literal:
            literal = True
        if token == '--next' and not literal:
            if not segments[-1]:
                raise ValueError('Segment ' + str(len(segments)) + ' is empty before --next')
            segments.append([])
        else:
            segments[-1].append(token)
    if len(segments) > 1 and not segments[-1]:
        raise ValueError('Segment ' + str(len(segments)) + ' is empty after --next')
    return segments


def parse_segments(parser, segments):
    """Parse every command before caller discovers or opens a database."""
    parsed, category = [], None
    for index, tokens in enumerate(segments, 1):
        try:
            options = tokens[:tokens.index('--')] if '--' in tokens else tokens
            if '--help' in options or '-h' in options:
                raise ValueError('Help is not executable in a chain; run the selected command with --help separately')
            args = parser.parse_args(tokens)
            if args.command in ('nodes', 'links', 'references'):
                selected = 'read'
                if args.command == 'links' and len(args.names) > 2:
                    raise ValueError('links accepts one or two node names')
            elif args.command in ('add', 'update', 'delete'):
                selected = 'write'
                if args.entity == 'evidence' and args.command in ('add', 'update'):
                    attachments = sum(hasattr(args, key) for key in ('node_id', 'edge_id'))
                    if attachments > 1 or (args.command == 'add' and attachments != 1):
                        raise ValueError('Evidence add requires exactly one parent; update permits at most one parent flag')
            else:
                raise ValueError('Only nodes/links/references or add/update/delete can form a chain; setup commands are excluded')
            if category is not None and category != selected:
                raise ValueError('Read and mutation commands cannot be mixed in one chain')
            category = selected
            parsed.append(args)
        except ValueError as exc:
            raise ValueError('Segment ' + str(index) + ': ' + str(exc)) from exc
    return parsed, category


def retry_command(segments, shell):
    argv = ['evomneme']
    for index, tokens in enumerate(segments):
        if index:
            argv.append('--next')
        argv.extend([tokens[0], '--all', *tokens[1:]] if index == 0 else tokens)
    if all(all(char.isprintable() and char not in '\u2028\u2029' for char in token) for token in argv):
        return quote_command(argv, shell)
    return 'Rerun the same chain with --all on a read segment before --, preserving the original literal arguments; control-bearing arguments have no copyable retry.'


def result_group(index, args, output):
    command = args.command + (' ' + args.entity if hasattr(args, 'entity') else '')
    header = '\n'.join(fields(dict(segment=index, command=command))) + '\nresult:\n'
    return header + ''.join(('  ' + line if line else '') + '\n' for line in output.splitlines())


def run(connection, parsed, category, segments):
    """Buffer all results; write chains commit only after aggregate validation."""
    active = None
    index = 1
    try:
        active = (ReadContext(connection, timeout=TIMEOUT_SECONDS) if category == 'read' else
                  MutationSession(connection, timeout=TIMEOUT_SECONDS))
        unlimited = category == 'read' and any(args.all_output for args in parsed)
        chunks, used = [], 0
        for index, args in enumerate(parsed, 1):
            active.check_time()
            if category == 'write':
                output = mutate(connection, args, session=active)
            elif args.command == 'references':
                output = references(connection, args.paths, all_output=True, shared=active)
            else:
                output = navigate(connection, args.command, args.names, all_output=True, shared=active)
            group = ('\n' if chunks else '') + result_group(index, args, output)
            used += len(group.encode('utf-8'))
            active.check_time()
            if not unlimited and used > OUTPUT_BYTES:
                retry = (' Full output: ' + retry_command(segments, connection.shell)) if category == 'read' else ''
                raise ValueError('Chain output exceeds 65536 UTF-8 bytes; no results emitted; writes rolled back.' + retry)
            chunks.append(group)
        output = ''.join(chunks)
        active.check_time()
        if category == 'write':
            active.commit()
        return output
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise ValueError('Segment ' + str(index) + ': ' + str(exc)) from exc
    finally:
        if active is not None:
            active.close()
