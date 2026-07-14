from virtualflex.ptt import K4PttMonitor


def test_backoff_grows_and_caps():
    seq, d = [], K4PttMonitor._MIN_BACKOFF
    for _ in range(8):
        seq.append(d)
        d = K4PttMonitor._next_backoff(d)
    assert seq == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0]
    assert max(seq) == K4PttMonitor._MAX_BACKOFF


def test_backoff_never_exceeds_cap():
    d = K4PttMonitor._MAX_BACKOFF
    assert K4PttMonitor._next_backoff(d) == K4PttMonitor._MAX_BACKOFF
