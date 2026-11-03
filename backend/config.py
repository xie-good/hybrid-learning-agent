"""服务端配置：默认本地 BM25 和带出处的原文摘录。"""
import os
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

# 从文件位置计算根目录，避免启动位置改变后读取错误的数据路径。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')

APP_NAME = os.getenv('APP_NAME', '课程学习助手')
DATA_DIR = PROJECT_ROOT / 'data'
COURSE_ID = 'hello_agents'
COURSE_NAME = '智能体系统设计与实现'


def should_trust_env(url: str) -> bool:
    """本机服务直接连接；远程服务仍遵循部署环境的代理配置。"""
    host = (urlsplit(url).hostname or '').rstrip('.').casefold()
    if host == 'localhost':
        return False
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:
        return True


def _path(name: str, default: Path) -> Path:
    """读取路径；空值使用默认路径，相对路径以项目根目录为起点。"""
    value = Path(os.getenv(name) or default).expanduser()
    return (PROJECT_ROOT / value).resolve()


@dataclass
class Settings:
    """保存配置默认值；服务启动时通过 from_env() 读取环境覆盖。"""

    # 数据路径：默认均在项目的 data 目录下。
    processed_dir: Path = DATA_DIR / 'processed/hello-agents'
    database_path: Path = DATA_DIR / 'runtime/history.sqlite3'
    index_dir: Path = DATA_DIR / 'indexes/hello-agents'
    source_pdf: Path | None = None

    # 运行模式：默认不依赖外部模型服务。
    generation_mode: str = 'extractive'
    default_retrieval_mode: str = 'bm25'

    # 可选的大模型生成服务。
    llm_base_url: str = ''
    llm_model: str = ''
    llm_api_key: str = ''

    # 可选的向量模型服务。
    embedding_base_url: str = ''
    embedding_model: str = ''
    embedding_api_key: str = ''

    # 模型请求超时和允许访问后端的前端地址。
    model_timeout: float = 30.0
    cors_origins: tuple[str, ...] = ('http://127.0.0.1:8501', 'http://localhost:8501')

    @classmethod
    def from_env(cls) -> 'Settings':
        """集中读取环境变量，并交给数据类统一校验。"""
        defaults = cls()
        try:
            timeout = float(os.getenv('MODEL_TIMEOUT', str(defaults.model_timeout)))
        except ValueError:
            raise ValueError('MODEL_TIMEOUT 必须填写数字，单位为秒。') from None
        origins = os.getenv('CORS_ORIGINS', ','.join(defaults.cors_origins)).split(',')

        return cls(
            processed_dir=_path('PROCESSED_DIR', defaults.processed_dir),
            database_path=_path('DATABASE_PATH', defaults.database_path),
            index_dir=_path('INDEX_DIR', defaults.index_dir),
            source_pdf=_path('SOURCE_PDF', PROJECT_ROOT) if os.getenv('SOURCE_PDF') else None,
            generation_mode=os.getenv('GENERATION_MODE', defaults.generation_mode),
            default_retrieval_mode=os.getenv('DEFAULT_RETRIEVAL_MODE', defaults.default_retrieval_mode),
            llm_base_url=os.getenv('LLM_BASE_URL', defaults.llm_base_url),
            llm_model=os.getenv('LLM_MODEL', defaults.llm_model),
            llm_api_key=os.getenv('LLM_API_KEY', defaults.llm_api_key),
            embedding_base_url=os.getenv('EMBEDDING_BASE_URL', defaults.embedding_base_url),
            embedding_model=os.getenv('EMBEDDING_MODEL', defaults.embedding_model),
            embedding_api_key=os.getenv('EMBEDDING_API_KEY', defaults.embedding_api_key),
            model_timeout=timeout,
            cors_origins=tuple(origin.strip() for origin in origins if origin.strip()),
        )

    def __post_init__(self):
        self.processed_dir = Path(self.processed_dir)
        self.database_path = Path(self.database_path)
        self.index_dir = Path(self.index_dir)
        if self.source_pdf is not None:
            self.source_pdf = Path(self.source_pdf)
        if self.generation_mode not in {'extractive', 'llm'}:
            raise ValueError('GENERATION_MODE 只能是 extractive 或 llm。')
        if self.default_retrieval_mode not in {'bm25', 'vector', 'hybrid'}:
            raise ValueError('DEFAULT_RETRIEVAL_MODE 只能是 bm25、vector 或 hybrid。')
        if not 0 < self.model_timeout <= 180:
            raise ValueError('MODEL_TIMEOUT 必须大于 0 且不超过 180 秒。')
