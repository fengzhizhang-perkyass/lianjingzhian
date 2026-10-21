"""Launch the native frontend and its Python adapter from any working directory."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='链境智安宣传首页与分析工作台')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    os.environ.setdefault('MPLCONFIGDIR', str(Path(os.environ.get('TMPDIR', '/tmp')) / 'web3aml-matplotlib'))
    try:
        import uvicorn
        import fastapi
    except ImportError:
        raise SystemExit('请先在 web3aml 环境执行：python -m pip install -r requirements-web.txt')
    from api.runtime_data import ensure_runtime_data
    try:
        ensure_runtime_data()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    print(f'链境智安首页：http://127.0.0.1:{args.port}/\n分析工作台：http://127.0.0.1:{args.port}/workspace\n保留的旧入口：streamlit run app.py', flush=True)
    uvicorn.run('api.main:app', host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
