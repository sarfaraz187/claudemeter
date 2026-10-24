const STALE_AFTER_SECONDS = 3600;

function formatRemaining(resetEpoch, nowEpoch) {
  if (typeof resetEpoch !== "number") return null;
  const secondsLeft = resetEpoch - nowEpoch;
  if (secondsLeft <= 0) return "now";
  const days = Math.floor(secondsLeft / 86400);
  const hours = Math.floor((secondsLeft % 86400) / 3600);
  const minutes = Math.floor((secondsLeft % 3600) / 60);
  if (days) return `in ${days}d ${hours}h`;
  if (hours) return `in ${hours}h ${minutes}m`;
  return `in ${minutes}m`;
}

function formatAge(ageSeconds) {
  const minutes = Math.floor(ageSeconds / 60);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m ago`;
}

export default {
  async fetch(request, env) {
    const providedSecret = request.headers.get("x-secret");

    if (request.method === "POST" && providedSecret === env.PUSH_SECRET) {
      const pushedUsage = JSON.parse(await request.text());
      pushedUsage.pushed_at = Math.floor(Date.now() / 1000);
      await env.USAGE.put("latest", JSON.stringify(pushedUsage));
      return new Response("ok");
    }

    if (request.method === "GET" && providedSecret === env.READ_SECRET) {
      const latestUsage = await env.USAGE.get("latest");
      if (latestUsage === null) {
        return new Response("no data yet", { status: 404 });
      }
      const usage = JSON.parse(latestUsage);
      const nowEpoch = Math.floor(Date.now() / 1000);
      const ageSeconds = nowEpoch - usage.pushed_at;
      usage.stale = usage.stale || ageSeconds > STALE_AFTER_SECONDS;
      usage.updated_ago = formatAge(ageSeconds);
      usage.session_reset_in = formatRemaining(usage.session_reset, nowEpoch);
      usage.week_reset_in = formatRemaining(usage.week_reset, nowEpoch);
      return new Response(JSON.stringify(usage), { headers: { "content-type": "application/json" } });
    }

    return new Response("forbidden", { status: 403 });
  },
};
