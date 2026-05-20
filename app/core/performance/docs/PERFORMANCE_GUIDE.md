# Performance Optimization Guide 🚀

For large-scale e-learning platforms on cPanel shared hosting.

---

## Quick Wins (Do These First)

### 1. Install Redis (If Available)

```bash
source ~/virtualenv/intellect-api.salesnet.ng/3.13/bin/activate
pip install redis asyncpg

# In your .env:
APP_CACHE_BACKEND=redis
APP_REDIS_URL=redis://localhost:6379/0
```

If Redis is not available, the system auto-falls back to in-memory LRU.

### 2. Add Performance Middleware to main.py

```python
from app.core.middleware import add_performance_middleware
 from app.core.performance.cache_config import cache import cache
from app.core.db_pool import init_db, close_db

# After app = FastAPI(...)
add_performance_middleware(app)

# Lifespan for cache/db init
@asynccontextmanager
async def lifespan(app: FastAPI):
    await cache.init()
    await init_db()
    yield
    await close_db()
    await cache.backend.close() if cache.backend else None

app = FastAPI(lifespan=lifespan, ...)
```

### 3. Add Health Check Router

```python
from app.api.health import router as health_router
app.include_router(health_router)
```

---

## Caching Strategy

### Route-Level Caching

```python
 from app.core.performance.cache_config import cache import cached, invalidate_cache

# Cache course listings for 10 minutes
@router.get("/courses")
@cached("courses:list", ttl=600)
async def list_courses(category_id: Optional[int] = None):
    return await course_service.get_all(category_id)

# Cache individual course for 1 hour
@router.get("/courses/{course_id}")
@cached("courses:detail", ttl=3600)
async def get_course(course_id: int):
    return await course_service.get_by_id(course_id)

# Invalidate on update
@router.put("/courses/{course_id}")
@invalidate_cache("courses")
async def update_course(course_id: int, data: CourseUpdate):
    return await course_service.update(course_id, data)
```

### Manual Cache Control

```python
 from app.core.performance.cache_config import cache import cache

# Pre-warm cache on startup
async def warm_cache():
    popular = await course_service.get_popular()
    await cache.set("courses:popular", popular, ttl=3600)

# Clear cache on data import
async def clear_course_cache():
    await cache.invalidate("courses")
```

---

## Database Optimization

### Connection Pooling (Already Configured)

```python
from app.core.db_pool import get_db_session

@router.get("/courses")
async def list_courses(session: AsyncSession = Depends(get_db_session)):
    # Session is automatically committed/closed
    result = await session.execute(select(Course))
    return result.scalars().all()
```

### Eager Loading (N+1 Prevention)

```python
from app.core.query_optimizer import QueryOptimizer

# BAD: N+1 queries
for course in courses:
    print(course.instructor.name)  # Queries per course!

# GOOD: One query with joins
query = select(Course)
query = QueryOptimizer.eager_load_courses(query)
result = await session.execute(query)
courses = result.scalars().all()
```

### Pagination

```python
from app.core.query_optimizer import QueryOptimizer

@router.get("/courses")
async def list_courses(page: int = 1, per_page: int = 20):
    query = select(Course).order_by(Course.created_at.desc())
    return await QueryOptimizer.paginated(session, query, page, per_page)
```

---

## Static File Optimization

### Build Optimized Assets

```bash
cd ~/intellect-api.salesnet.ng
python app/core/static_optimizer.py static static/dist
```

This generates:
- `app.a1b2c3d4.js` (hashed filename for cache busting)
- `app.js.gz` (pre-compressed for nginx)
- `manifest.json` (for template rendering)

### Serve via FastAPI

```python
from fastapi.staticfiles import StaticFiles

# In production, serve optimized assets
app.mount("/static", StaticFiles(directory="static/dist"), name="static")
```

### Cache Headers (Already in Middleware)

```
Cache-Control: public, max-age=31536000, immutable  # For hashed files
Cache-Control: public, max-age=3600, must-revalidate  # For named assets
```

---

## Request Coalescing (Thundering Herd Prevention)

When cache expires and 100 users hit the same endpoint simultaneously:

```
Without coalescing: 100 database queries
With coalescing: 1 database query, 99 wait for result
```

Already enabled in `add_performance_middleware()`.

---

## Health Checks for Load Balancers

| Endpoint | Use | Response |
|----------|-----|----------|
| `GET /health` | Liveness probe | 200 if process up |
| `GET /health/deep` | Dependency check | 200 if DB+cache OK, 503 if degraded |
| `GET /health/ready` | Readiness probe | 200 only when ready for traffic |
| `GET /health/metrics` | Monitoring | CPU, memory, disk stats |

### cPanel/.htaccess Load Balancer Config

```apache
# Health check for load balancer
RewriteRule ^/health$ http://localhost:8001/health [P,L]

# Only route traffic if ready
# (Configure in cPanel Application Manager or ask host)
```

---

## Environment Variables

```bash
# .env — Performance tuning

# Cache
APP_CACHE_BACKEND=redis          # or "memory"
APP_REDIS_URL=redis://localhost:6379/0
APP_CACHE_TTL=300                # Default 5 minutes
APP_CACHE_MAXSIZE=10000          # LRU max items

# Database Pool
DB_POOL_SIZE=10                  # Base connections
DB_MAX_OVERFLOW=20               # Burst connections
DB_POOL_RECYCLE=3600             # Recycle after 1 hour
DB_POOL_TIMEOUT=30               # Wait for connection

# Gunicorn (already in deploy/config.env)
WORKERS=auto
MAX_REQUESTS=1000                # Recycle workers (memory leak guard)
MAX_REQUESTS_JITTER=100          # Stagger recycling
```

---

## Performance Checklist

- [ ] Redis installed and connected (or memory fallback)
- [ ] `add_performance_middleware()` called in main.py
- [ ] `@cached()` on read-heavy endpoints (courses, categories)
- [ ] `@invalidate_cache()` on write endpoints
- [ ] `QueryOptimizer.eager_load_*` on all list queries
- [ ] Pagination on all list endpoints (default 20/page)
- [ ] Static files optimized and hashed
- [ ] Health checks responding correctly
- [ ] `DB_POOL_SIZE` tuned for worker count
- [ ] `MAX_REQUESTS` set to recycle workers

---

## Benchmarking

```bash
# Install Apache Bench
# Test endpoint performance
ab -n 1000 -c 50 http://localhost:8001/api/v1/courses

# With cache (should be 10x+ faster)
ab -n 1000 -c 50 http://localhost:8001/api/v1/courses

# Check response times in logs
tail -f logs/app.log | grep "Slow request"
```

---

## Monitoring Dashboard

Set up `monitor.sh` cron to check `/health/deep`:

```bash
crontab -e
# Add:
*/5 * * * * bash /home/salesne2/intellect-api.salesnet.ng/deploy/monitor.sh
```

---

**Expected Performance Gains:**

| Metric | Before | After |
|--------|--------|-------|
| Course list (cached) | ~200ms | ~5ms |
| Course detail (cached) | ~150ms | ~2ms |
| Database queries (N+1) | N queries | 1 query |
| Static assets | No cache | 1 year immutable |
| Worker memory | Unbounded | Recycled every 1k requests |
