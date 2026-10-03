from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import engine_from_config,pool
from wedding_ops.models import Base
config=context.config
if config.config_file_name:fileConfig(config.config_file_name)
url=os.getenv('WEDDINGOPS_DATABASE_URL',config.get_main_option('sqlalchemy.url'))
config.set_main_option('sqlalchemy.url',url.replace('%','%%'))
target_metadata=Base.metadata
if context.is_offline_mode():
    context.configure(url=url,target_metadata=target_metadata,literal_binds=True,dialect_opts={'paramstyle':'named'})
    with context.begin_transaction():context.run_migrations()
else:
    connectable=engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
