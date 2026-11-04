"""Run from the configured runtime: python check_cloud.py. Never prints secrets."""
from cloud_store import CloudStorageError, SupabaseStore

if __name__ == "__main__":
    try:
        SupabaseStore().verify()
        print("Supabase 元数据表与私有文件存储连接正常。")
    except CloudStorageError as exc:
        print(str(exc))
        raise SystemExit(1)
