"""Start exactly one local backend, serving the production frontend build."""
from .settings import Settings
if __name__=='__main__':
    import uvicorn
    settings=Settings()
    uvicorn.run('website.app:app',host=settings.host,port=settings.port,workers=1)
