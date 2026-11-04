from workbench.config import setting,cloud_runtime
from workbench.storage.local import LocalStore
from workbench.storage.cloud import CloudStore,StorageError


def open_store():
    backend=setting('STORAGE_BACKEND','local').lower()
    if backend=='supabase':
        store=CloudStore()
        store.verify()
        return store
    if backend!='local':raise StorageError('STORAGE_BACKEND 仅支持 local 或 supabase。')
    if cloud_runtime():raise StorageError('请为云端配置 STORAGE_BACKEND=supabase。')
    return LocalStore()
