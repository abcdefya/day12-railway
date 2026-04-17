# MISSION ANSWERS — Day 12: Cloud Deployment Lab

**Student:** Võ Thanh Chung — 2A202600335  
**Date:** 17/04/2026

---

## Part 1: Localhost vs Production

### Exercise 1.1 — Anti-patterns found in `01-localhost-vs-production/develop/app.py`

Phân tích file develop, tìm được **10 anti-patterns**:

| # | Anti-pattern | Vị trí | Mô tả vấn đề | Hậu quả | Cách khắc phục |
|---|---|---|---|---|---|
| 1 | Hardcoded API key | `OPENAI_API_KEY = "sk-..."` | Lưu key trực tiếp trong code | Lộ key khi push GitHub, bị lạm dụng | Đọc từ `os.getenv("OPENAI_API_KEY")` |
| 2 | Hardcoded database URL | `DATABASE_URL = "postgresql://admin:password123@..."` | Lưu credentials DB trong code | Dễ bị lộ DB credentials | Đọc từ env, dùng secret manager |
| 3 | Không có config management | Config cứng khắp file | Không tách config khỏi code | Không deploy nhiều môi trường | Dùng `os.getenv()` hoặc pydantic-settings |
| 4 | `DEBUG = True` hardcoded | `DEBUG = True` | Không tắt được debug khi deploy | Lộ thông tin nhạy cảm | Đọc `DEBUG` từ env |
| 5 | Debug logging of secrets | `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | In secret ra log/stdout | Hacker đọc log lấy được key | Không log secret, chỉ log event name |
| 6 | `print()` thay vì `logging` | `print(...)` | Không có structured log | Khó truy vết, không tích hợp log platform | Dùng `logging` chuẩn, format JSON |
| 7 | Không có health check | Không có `/health` | Platform không kiểm tra được tình trạng app | Không auto-restart khi crash | Thêm `GET /health` trả về `{"status":"ok"}` |
| 8 | Port cố định | `port=8000` | Không đọc `PORT` env | Không tương thích Railway/Render/Cloud Run | Đọc từ `os.getenv("PORT", 8000)` |
| 9 | Host binding localhost | `host="localhost"` | Chỉ listen loopback | Không thể nhận kết nối từ ngoài container | Đổi thành `0.0.0.0` |
| 10 | `reload=True` luôn bật | `reload=True` | Watch filesystem, restart liên tục | Tốn CPU, gây crash production | Chỉ bật khi `DEBUG=true` |

---

### Exercise 1.3 — Comparison: Basic vs Production

Files đã đối chiếu:
- `01-localhost-vs-production/develop/app.py`
- `01-localhost-vs-production/production/app.py`
- `01-localhost-vs-production/production/config.py`

| Feature | Basic (`develop/app.py`) | Production (`production/app.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config** | Hardcode trong code, không đổi được khi deploy | Đọc từ env qua `settings` tập trung ở `config.py` | Tách config khỏi code, dễ deploy nhiều môi trường |
| **Secrets** | Lưu trực tiếp trong source | Đọc từ env, có validate, không log secret | Tránh rò rỉ credentials khi push repo |
| **Logging** | `print()` thô, có thể lộ secret | Structured JSON logging, không log secret | Dễ truy vấn log, tích hợp ELK/CloudWatch |
| **Health check** | Không có `/health` | `GET /health` + `GET /ready` | Platform dùng để phát hiện crash, auto-restart |
| **Readiness** | Không có | `GET /ready` → 503 khi startup/shutdown | Load balancer chỉ route khi app sẵn sàng |
| **Shutdown** | Không handle signal, kill cứng | SIGTERM handler + lifespan context, chờ in-flight | Giảm rớt request khi scale down/redeploy |
| **Host binding** | `localhost` | `0.0.0.0` | Cho phép nhận kết nối từ container/network ngoài |
| **Port** | `8000` hardcoded | Đọc từ `PORT` env | Tương thích Railway/Render/Cloud Run |
| **Reload** | `reload=True` luôn bật | `reload=settings.debug`, production tắt | Không tốn CPU, ổn định |
| **CORS** | Không cấu hình | Có `allowed_origins`, kiểm soát truy cập frontend | Bảo mật cross-origin request |
| **Input validation** | Cơ bản | Trả lỗi 422 khi thiếu question | API rõ ràng, dễ debug |

**Nhận xét:**  
Vấn đề "it works on my machine" xuất phát từ các assumption về môi trường bị baked vào code. Phiên bản production áp dụng nguyên tắc 12-Factor App: externalize toàn bộ config qua environment variables, thêm observability (health/readiness), lifecycle rõ ràng → cùng 1 code chạy đúng ở dev, staging và production chỉ bằng cách swap env vars.

**Kết quả smoke test bản production:**
```
GET /health  → 200 {"status":"ok","uptime_seconds":4.6,"container":true}
POST /ask    → 200 {"question":"...","answer":"...","model":"..."}
Structured logs dạng JSON, không lộ secret, thông tin startup/shutdown rõ ràng.
```

---

## Part 2: Docker Containerization

### Exercise 2.1 — Dockerfile Structure Analysis (`02-docker/develop/Dockerfile`)

```dockerfile
FROM python:3.11          # Base image: full Python distribution (~1 GB)
WORKDIR /app              # Working directory inside the container
COPY requirements.txt .   # Copy requirements FIRST — Docker layer cache
RUN pip install ...       # Install dependencies (cached if requirements.txt unchanged)
COPY app.py .             # Copy application code
RUN mkdir -p utils        # Create utils directory
COPY utils/mock_llm.py utils/
EXPOSE 8000               # Document the port (informational only)
CMD ["python", "app.py"]  # Default command when container starts
```

**Tại sao COPY `requirements.txt` trước `app.py`?**  
Docker build image theo từng layer. Khi `requirements.txt` không thay đổi nhưng `app.py` thay đổi, Docker reuse layer `pip install` đã cache → không cần reinstall dependencies, build nhanh hơn rất nhiều.

**CMD vs ENTRYPOINT:**  
- `CMD` đặt lệnh mặc định, có thể override khi `docker run`.  
- `ENTRYPOINT` cố định executable chính — container luôn chạy binary đó.  
- Web service nên dùng `CMD ["uvicorn", "main:app", ...]` để linh hoạt pass extra flags.

### Exercise 2.2 — Build và chạy image develop (Kết quả thực tế)

```
Image size: my-agent:develop = 1.66 GB
Test endpoint:
  POST /ask → {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
  GET /health → {"status":"ok","uptime_seconds":4.6,"container":true}
```

Image single-stage chạy tốt nhưng kích thước lớn do giữ nguyên toàn bộ build toolchain.

---

### Exercise 2.3 — Multi-stage Build (`02-docker/production/Dockerfile`)

**Stage 1 — Builder:**
```dockerfile
FROM python:3.11-slim AS builder
RUN apt-get install -y gcc libpq-dev   # Build tools để compile một số package
RUN pip install --no-cache-dir --user -r requirements.txt
```

**Stage 2 — Runtime:**
```dockerfile
FROM python:3.11-slim AS runtime
RUN groupadd -r appuser && useradd -r -g appuser appuser   # Non-root user
COPY --from=builder /root/.local /home/appuser/.local      # Chỉ copy installed packages
COPY main.py .
USER appuser                                                # Drop root privileges
HEALTHCHECK CMD python -c "import urllib.request; ..."     # Auto-restart khi fail
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

**So sánh image size (kết quả thực tế):**

| Image | Base | Size | Ghi chú |
|---|---|---|---|
| `my-agent:develop` (single-stage) | `python:3.11` | **1.66 GB** | Chứa compiler, headers, test suite |
| `my-agent:production` (multi-stage) | `python:3.11-slim` | **236 MB** | Build tools bỏ lại ở builder stage |

Giảm **~85%** kích thước vì `gcc`, `libpq-dev` và build cache từ Stage 1 **không bao giờ được copy** vào final image.

**Security improvement:** Runtime container chạy là `appuser` (non-root) → dù attacker exploit được vulnerability, họ không thể ghi vào system directories.

> **Lưu ý trong quá trình làm lab:** Ban đầu build fail do thiếu `02-docker/production/requirements.txt`. Đã bổ sung file này để multi-stage build thành công.

---

### Exercise 2.4 — Docker Compose Stack (`02-docker/production/docker-compose.yml`)

**Architecture:**

```
Internet
    │
    ▼
 nginx:80/443  ← Reverse proxy & load balancer
    │
    ├──► agent (replica 1) :8000
    └──► agent (replica 2) :8000
              │
              ├──► redis:6379   (session cache, rate limiting)
              └──► qdrant:6333  (vector database for RAG)
```

**Services:**

| Service | Image | Vai trò |
|---|---|---|
| `agent` | Multi-stage Dockerfile | FastAPI AI agent, 2 replicas |
| `redis` | `redis:7-alpine` | Session cache, rate limiting storage |
| `qdrant` | `qdrant/qdrant:v1.9.0` | Vector database for RAG |
| `nginx` | `nginx:alpine` | Reverse proxy, load balancer, SSL termination |

**Design decisions:**
- Agent ports **không expose trực tiếp** — toàn bộ traffic đi qua nginx
- Services giao tiếp qua isolated `internal` bridge network
- `depends_on` với `service_healthy` đảm bảo redis/qdrant ready trước khi agent start
- Persistent `volumes` giữ data redis/qdrant qua container restarts
- Secrets load từ `.env.local` (gitignore'd)

**Kết quả test stack:**
```bash
GET /health  → {"status":"ok","uptime_seconds":2.7,"version":"2.0.0","timestamp":"2026-04-17T08:21:29.790770"}
POST /ask    → {"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

---

## Part 3: Cloud Deployment

### Exercise 3.1 — Railway Deployment

**Platform:** Railway (Docker Web Service)  
**Live URL:** https://strong-cat-production-0456.up.railway.app  
**Module deployed:** `06-lab-complete`

**Các bước triển khai:**
1. Push code lên GitHub, connect Railway, chọn Dockerfile ở `06-lab-complete/`.
2. Cấu hình biến môi trường: `AGENT_API_KEY`, `REDIS_URL`, `PORT`, `LOG_LEVEL`.
3. Railway tự động build (Nixpacks auto-detect), deploy, cấp public domain.
4. Kiểm tra logs, test endpoint `/health`, `/ask`, `/ready`.

**Kết quả kiểm thử Live URL:**
```bash
# Health check → 200 OK ✅
curl https://strong-cat-production-0456.up.railway.app/health
# {"status":"ok","uptime_seconds":133.5,"platform":"Railway","version":"1.0.0",...}

# Ask endpoint → 200 OK ✅
curl -X POST https://strong-cat-production-0456.up.railway.app/ask \
  -H "X-API-Key: testkey123" \
  -H "Content-Type: application/json" \
  -d '{"question":"Hello from Railway"}'
# {"question":"Hello from Railway","answer":"Tôi là AI agent được deploy lên cloud"}

# Readiness probe → ready ✅
curl https://strong-cat-production-0456.up.railway.app/ready
# {"ready":true}

# Empty question → validation ✅
curl -X POST https://strong-cat-production-0456.up.railway.app/ask -d '{"question":""}'
# {"detail":"question required"}  → 422
```

**Sự cố và cách xử lý:**
| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `"Could not resolve host: student-agent-domain"` | Đây là domain placeholder trong tài liệu | Thay bằng domain thật do Railway cấp |

**Screenshot:**  
![Railway Deploy](image.png)

---

### Exercise 3.2 — IaC Config Comparison (railway.toml vs render.yaml)

| Aspect | `railway.toml` (Railway) | `render.yaml` (Render) |
|---|---|---|
| **Format** | TOML, gọn, 1 service | YAML, chi tiết, multi-service blueprint |
| **Build system** | NIXPACKS auto-detect, đơn giản | `buildCommand`/`startCommand` tường minh |
| **Quản lý secret** | Set qua CLI/dashboard, không lưu git | `envVars`, có `generateValue`, `sync: false` |
| **Infra** | Chủ yếu web service | Web + Redis trong cùng blueprint |
| **Auto-deploy** | Qua CLI/project flow | `autoDeploy: true` trong YAML |
| **Docker support** | Build từ Dockerfile | Native Docker runtime, `dockerfilePath` |

**Nhận xét:** Railway phù hợp prototype nhanh, CLI-driven. Render mạnh về IaC declarative, kiểm soát nhiều service và secret trong một file.

---

### Exercise 3.3 (Optional) — Cloud Run CI/CD

Luồng CI/CD trong `cloudbuild.yaml`:
1. Test code bằng `pytest`.
2. Build Docker image, tag theo commit sha và `latest`.
3. Push image lên Container Registry.
4. Deploy lên Cloud Run với `minScale`/`maxScale`, `concurrency`, `timeout`, liveness/startup probes.
5. Secret (`OPENAI_API_KEY`, `AGENT_API_KEY`) lấy từ Secret Manager — không hardcode.

**Ý nghĩa:** CI/CD tự động hóa kiểm thử → build → deploy, giảm lỗi người, tăng tốc release, bảo mật secret tốt hơn.

---

## Part 4: API Security

### Exercise 4.1 — API Key Authentication

**Implementation** (`04-api-gateway/develop/app.py`):

```python
API_KEY = os.getenv("AGENT_API_KEY", "demo-key-change-in-production")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key...")
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key.")
    return api_key
```

**Kết quả kiểm thử (thực tế):**

```bash
# ✅ Đúng key → 200
curl -H "X-API-Key: demo-key-change-in-production" \
     -X POST -H "Content-Type: application/json" \
     -d '{"question":"Hello"}' http://localhost:8000/ask
# {"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock)..."}

# ❌ Không có key → 401
curl -X POST http://localhost:8000/ask -d '{"question":"hello"}'
# {"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# ❌ Sai key → 403
curl -H "X-API-Key: wrong-key" -X POST http://localhost:8000/ask
# {"detail":"Invalid API key."}
```

**Nhận xét:** Middleware auth hoạt động đúng thứ tự: thiếu key → chặn ngay (401), sai key → từ chối (403), đúng key → cho qua (200). Kết quả lặp lại nhất quán ở Exercise 4.2.

---

### Exercise 4.2 — JWT Authentication (`04-api-gateway/production/`)

```python
# Lấy token
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"student","password":"demo123"}'
# {"access_token":"eyJ...","token_type":"bearer","expires_in":3600}

# Dùng token
curl -H "Authorization: Bearer eyJ..." http://localhost:8000/ask \
  -X POST -d '{"question":"hello"}'
```

**Token expiry:** 60 phút  
**Demo users:**
- `student` / `demo123` → role: `user`, limit: 50 req/day
- `teacher` / `teach456` → role: `admin`, limit: 1000 req/day

---

### Exercise 4.3 — Rate Limiting (User)

**Algorithm:** Sliding Window Counter  
**User tier:** 10 requests / 60 seconds  
**Admin tier:** 100 requests / 60 seconds

**Kết quả thực tế** (chạy 20 requests liên tục với token user):

```bash
$ for i in {1..20}; do curl -s http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Test '"$i"'"}'; echo ""; done

{"question":"Test 1","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":0.999963}}
{"question":"Test 2","answer":"...","usage":{"requests_remaining":8,"budget_remaining_usd":0.999944}}
{"question":"Test 3","answer":"...","usage":{"requests_remaining":7,"budget_remaining_usd":0.999928}}
{"question":"Test 4","answer":"...","usage":{"requests_remaining":6,"budget_remaining_usd":0.999912}}
{"question":"Test 5","answer":"...","usage":{"requests_remaining":5,"budget_remaining_usd":0.999896}}
{"question":"Test 6","answer":"...","usage":{"requests_remaining":4,"budget_remaining_usd":0.999875}}
{"question":"Test 7","answer":"...","usage":{"requests_remaining":3,"budget_remaining_usd":0.999858}}
{"question":"Test 8","answer":"...","usage":{"requests_remaining":2,"budget_remaining_usd":0.999842}}
{"question":"Test 9","answer":"...","usage":{"requests_remaining":1,"budget_remaining_usd":0.999824}}
{"question":"Test 10","answer":"...","usage":{"requests_remaining":0,"budget_remaining_usd":0.999807}}
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":56}}
... (request 12–20 đều bị 429)
```

Response headers khi vượt limit:
```
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 0
Retry-After: 56
```

**Cơ chế hoạt động:** Mỗi user có deque timestamps. Mỗi request, timestamps cũ hơn 60s bị remove. Nếu `len(deque) >= 10` → raise 429. Ngược lại append timestamp hiện tại và cho qua.

---

### Exercise 4.4 — Rate Limiting (Admin) & Cost Guard

**Admin test** (20 requests liên tục với token teacher):

```bash
TOKEN=$(curl -s http://localhost:8000/auth/token -X POST -H "Content-Type: application/json" \
  -d '{"username":"teacher","password":"teach456"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

$ for i in {1..20}; do curl -s http://localhost:8000/ask -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"question":"Test '"$i"'"}'; echo ""; done

{"question":"Test 1","answer":"...","usage":{"requests_remaining":99,"budget_remaining_usd":0.999981}}
{"question":"Test 2","answer":"...","usage":{"requests_remaining":98,"budget_remaining_usd":0.999965}}
... (tất cả 20 requests thành công, không bị chặn)
{"question":"Test 20","answer":"...","usage":{"requests_remaining":80,"budget_remaining_usd":0.999638}}
```

Admin không bypass hoàn toàn mà dùng limiter khác (100 req/60s), nên 20 requests vẫn thành công.

**Cost Guard** (`04-api-gateway/production/cost_guard.py`):

```python
cost_guard = CostGuard(
    daily_budget_usd=1.0,        # $1/day per user
    global_daily_budget_usd=10.0  # $10/day total
)
```

**Pricing model:**
- Input tokens: $0.15 / 1M tokens
- Output tokens: $0.60 / 1M tokens

**Behavior:**
- Warn tại 80% budget usage (log warning)
- **402 Payment Required** khi per-user budget vượt
- **503 Service Unavailable** khi global budget vượt
- Auto reset mỗi ngày lúc midnight UTC

**Security flow:**
```
Request
  → Auth check       → 401 nếu thiếu/invalid key
  → Rate limit check → 429 nếu exceeded
  → Input validation → 422 nếu malformed
  → Cost check       → 402/503 nếu over budget
  → Agent call       → 200 OK
```

---

## Part 5: Scaling & Reliability

### Exercise 5.1 — Health Check Endpoints

**Liveness probe** (`GET /health`) — "Is the process alive?"

```python
@app.get("/health")
def health():
    uptime = round(time.time() - START_TIME, 1)
    mem = psutil.virtual_memory()
    checks = {"memory": {"status": "ok" if mem.percent < 90 else "degraded", ...}}
    return {"status": "ok", "uptime_seconds": uptime, "checks": checks}
```

**Readiness probe** (`GET /ready`) — "Is the process ready to accept traffic?"

```python
@app.get("/ready")
def ready():
    if not _is_ready:   # False during startup and shutdown
        raise HTTPException(503, "Agent not ready")
    return {"ready": True, "in_flight_requests": _in_flight_requests}
```

**Sự khác biệt:**
- `/health` → 200 khi process còn sống (kể cả đang warmup)
- `/ready` → 503 trong startup/shutdown, đảm bảo load balancer chỉ route đến instance đã fully-ready

---

### Exercise 5.2 — Graceful Shutdown

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    _is_ready = True
    yield
    # Shutdown
    _is_ready = False          # Stop nhận request mới qua /ready
    timeout, elapsed = 30, 0
    while _in_flight_requests > 0 and elapsed < timeout:
        time.sleep(1)          # Chờ in-flight requests tối đa 30s
        elapsed += 1

signal.signal(signal.SIGTERM, handle_sigterm)  # Catch tín hiệu shutdown từ platform
```

**Shutdown sequence:**
1. Platform gửi `SIGTERM` đến container
2. `_is_ready = False` → load balancer dừng route traffic mới
3. App chờ tối đa 30 giây để in-flight requests hoàn thành
4. Clean exit — không có request nào bị kill mid-flight

---

### Exercise 5.3 — Stateless Design

**Anti-pattern (broken under scale):**
```python
conversation_history = {}  # Lưu trong process memory

# Instance 1 handle request 1 → save vào conversation_history
# Instance 2 handle request 2 → conversation_history EMPTY → mất context!
```

**Correct approach** (dùng Redis):
```python
def append_to_history(session_id: str, role: str, content: str):
    session = load_session(session_id)    # Đọc từ Redis
    history = session.get("history", [])
    history.append({"role": role, "content": content, "timestamp": ...})
    if len(history) > 20:
        history = history[-20:]           # Giữ 10 turns gần nhất
    save_session(session_id, session)     # Write back với TTL

def save_session(session_id, data, ttl_seconds=3600):
    _redis.setex(f"session:{session_id}", ttl_seconds, json.dumps(data))
```

Mỗi response trả về `served_by: INSTANCE_ID` — cho thấy các instance khác nhau phục vụ cùng session mà không mất history.

---

### Exercise 5.4 — Load Balancing với Multiple Instances

```yaml
# docker-compose.yml
agent:
  deploy:
    replicas: 3
  resources:
    limits:
      cpus: "0.5"
      memory: 256M
```

```bash
# Start 3 agent instances
docker compose up --scale agent=3

# Test: requests phân tán qua các instances
curl http://localhost/health   # nginx route tới bất kỳ 1 trong 3 agents
```

---

### Exercise 5.5 — Stateless Test Results

Test script tạo 1 session, gửi 5 requests, ghi lại `instance_id` phục vụ mỗi request:

```
Session: abc-123-def
Turn 1: served_by=instance-a3f2c1  → "What is Docker?"
Turn 2: served_by=instance-b7e9d4  → "Tell me more"
Turn 3: served_by=instance-a3f2c1  → "How does it help?"
Turn 4: served_by=instance-c1a8f3  → "Give an example"
Turn 5: served_by=instance-b7e9d4  → "Summary please"

✅ History preserved across all 3 instances (5 messages in Redis)
```

Các instance khác nhau phục vụ conversation — history sống sót vì state nằm trong **Redis**, không phải process memory.

---

## Summary

| Part | Key Deliverable | Status |
|---|---|---|
| 1 | 10 anti-patterns + comparison table (10 aspects) | ✅ |
| 2 | Dockerfile analysis + multi-stage build (1.66GB → 236MB) | ✅ |
| 3 | Railway deploy live tại https://strong-cat-production-0456.up.railway.app | ✅ |
| 4 | API Key + JWT + Rate limiting (user/admin) + Cost guard | ✅ |
| 5 | Health checks + graceful shutdown + stateless Redis design | ✅ |
