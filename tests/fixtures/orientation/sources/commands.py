from protocol import prepare


def confirm(draft, request_id, ledger, send):
    payload = ledger.pending(request_id)
    if payload is None:
        reference, payload = prepare(draft.reference, draft.items)
        ledger.commit(request_id, reference, payload)
    # A timeout leaves the original bytes pending, even if the draft is edited.
    response = send(request_id, payload)
    ledger.acknowledge(request_id)
    return response
