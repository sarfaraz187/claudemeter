const STALE_AFTER_SECONDS = 3600;

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
      const ageSeconds = Math.floor(Date.now() / 1000) - usage.pushed_at;
      usage.stale = usage.stale || ageSeconds > STALE_AFTER_SECONDS;
      return new Response(JSON.stringify(usage), { headers: { "content-type": "application/json" } });
    }

    return new Response("forbidden", { status: 403 });
  },
};
