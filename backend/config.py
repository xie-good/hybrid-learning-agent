"""集中管理路径与配置。此阶段不连接模型、数据库或向量库。"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 从文件位置计算根目录，避免启动位置改变后读取错误的数据路径。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')

APP_NAME = os.getenv('APP_NAME', '课程学习助手')
DATA_DIR = PROJECT_ROOT / 'data'
COURSE_ID = 'hello_agents'
COURSE_NAME = '智能体系统设计与实现'
