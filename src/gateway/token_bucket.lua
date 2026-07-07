-- Atomic token-bucket rate limiter, run inside.
--
-- KEYS[1] = bucket key, e.g. "rate_limit:1.2.3.4"
-- ARGV[1] = capacity      (max tokens the bucket can hold)
-- ARGV[2] = refill_rate   (tokens added per second)
-- ARGV[3] = now           (current unix time in seconds, passed by the app)
-- ARGV[4] = requested     (tokens this request costs, usually 1)
--
-- Returns: { allowed (1/0), retry_after_seconds }

local capacity    = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now         = tonumber(ARGV[3])
local requested   = tonumber(ARGV[4])

-- Read current state of the bucket (a Redis hash with two fields).
local bucket = redis.call("HMGET", KEYS[1], "tokens", "ts")
local tokens = tonumber(bucket[1])
local last   = tonumber(bucket[2])

-- First time we've seen this key: start with a full bucket.
if tokens == nil then
    tokens = capacity
    last   = now
end

-- Refill: add however many tokens accrued since we last touched the bucket,
-- but never overflow past capacity.
local elapsed = math.max(0, now - last)
tokens = math.min(capacity, tokens + (elapsed * refill_rate))

-- Decide.
local allowed = 0
local retry_after = 0
if tokens >= requested then
    allowed = 1
    tokens = tokens - requested
else
    -- How long until enough tokens have refilled to serve this request?
    retry_after = (requested - tokens) / refill_rate
end

-- Persist new state and expire idle buckets so Redis doesn't fill with keys.
redis.call("HSET", KEYS[1], "tokens", tokens, "ts", now)
local ttl = math.ceil(capacity / refill_rate) * 2
redis.call("EXPIRE", KEYS[1], ttl)

return { allowed,retry_after }
