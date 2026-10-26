import json


def prepare(reference, items):
    normalized = ''.join(reference.split()).upper()
    payload = json.dumps({'reference': normalized, 'items': items},
                         sort_keys=True, separators=(',', ':')).encode('utf-8')
    return normalized, payload
