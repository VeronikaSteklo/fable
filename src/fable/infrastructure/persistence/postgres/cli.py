"""Apply bundled migrations without requiring any LLM credentials."""
import argparse
import os

from psycopg_pool import ConnectionPool

from fable.infrastructure.persistence.postgres import migrate


def main() -> None:
    parser = argparse.ArgumentParser(description='Миграции схемы PostgreSQL Fable')
    parser.add_argument('--database-url', default=os.environ.get('DATABASE_URL'),
                        help='По умолчанию DATABASE_URL из окружения')
    args = parser.parse_args()
    if not args.database_url:
        parser.error('Укажи DATABASE_URL или --database-url')
    with ConnectionPool(args.database_url, min_size=1, max_size=1, open=True,
                        kwargs={'options': '-c timezone=UTC'}) as pool:
        pool.wait(timeout=15)
        migrate(pool)
    print('Миграции PostgreSQL применены')


if __name__ == '__main__':
    main()
