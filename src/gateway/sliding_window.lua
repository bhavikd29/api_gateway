-- sliding_window.lua
-- Sliding-window-LOG rate limiter, run atomically inside Redis.
-- Each client is a sorted set (ZSET): member = unique request id, score = timestamp.
--
-- KEYS[1] = client key, e.g. "rate_limit:sw:1.2.3.4"
-- ARGV[1] = now      (current unix timestamp, passed by the app)
-- ARGV[2] = window   (window size in seconds, e.g. 60)
-- ARGV[3] = limit    (max requests allowed within the window)
-- ARGV[4] = req_id   (unique id for THIS request, e.g. a uuid from Python)
--
-- Returns: { allowed (1/0), retry_after_seconds }

local now    = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit  = tonumber(ARGV[3])
local req_id = ARGV[4]

-- 1. TRIM: drop entries older than the window (score < now - window).
--    "(" makes the upper bound exclusive, so a request exactly at the edge stays.
redis.call("ZREMRANGEBYSCORE", KEYS[1], "-inf", "(" .. (now - window))

-- 2. COUNT: how many requests remain inside the window.
local count = redis.call("ZCARD", KEYS[1])

-- 3 + 4. DECIDE and RECORD / compute RETRY.
local allowed = 0
local retry_after = 0
if count < limit then
    allowed = 1
    redis.call("ZADD", KEYS[1], now, req_id)
else
    -- Oldest surviving entry: when it slides out, a slot frees up.
    local oldest = redis.call("ZRANGE", KEYS[1], 0, 0, "WITHSCORES")
    local oldest_score = tonumber(oldest[2])
    retry_after = (oldest_score + window) - now
end

-- 5. CLEANUP: expire idle clients after 2 windows; a returning client starts
--    empty, which is correct because everything would have aged out anyway.
redis.call("EXPIRE", KEYS[1], math.ceil(window * 2))

-- 6. RETURN
return { allowed, retry_after }
