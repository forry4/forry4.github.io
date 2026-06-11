import importlib, traceback, inspect, types

def inspect_module(name: str):
    try:
        m = importlib.import_module(name)
    except Exception:
        traceback.print_exc()
        return
    print('module file:', getattr(m, '__file__', None))
    print('__spec__:', getattr(m, '__spec__', None))
    print('__loader__:', getattr(m, '__loader__', None))
    keys = list(m.__dict__.keys())
    print('total keys:', len(keys))
    print('sample keys:', keys[:80])
    # count public keys
    public = [k for k in keys if not k.startswith('_')]
    print('public keys count:', len(public))
    print('public keys:', public[:80])
    for name in ['app','GEM_COLORS','create_game','ws_endpoint']:
        print(f"{name}:", name in m.__dict__)
    if 'app' in m.__dict__:
        try:
            print('app title =>', m.app.title)
        except Exception:
            print('app present but accessing attributes failed')

    # also run the file directly to see what globals would be created
    try:
        import runpy
        print('\n--- runpy.run_path output keys ---')
        rp = runpy.run_path(m.__file__, run_name='__main__')
        rp_keys = [k for k in rp.keys() if not k.startswith('_')]
        print('run_path public keys count:', len(rp_keys))
        print('run_path sample keys:', rp_keys[:80])
    except Exception:
        print('run_path execution failed:')
        traceback.print_exc()

if __name__ == '__main__':
    inspect_module('Spender.main')
