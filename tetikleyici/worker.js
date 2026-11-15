// Tarife Radarı dış zamanlayıcısı (Cloudflare Workers, ücretsiz plan).
//
// GitHub'ın kendi cron'u yoğunlukta seyreltildiği için (gerçekte günde 3-4 tur) radar turu
// buradan 30 dakikada bir workflow_dispatch ile başlatılır. Worker'ın herkese açık bir adresi
// yoktur (wrangler.toml: workers_dev = false, rota yok); yalnızca zamanlayıcıyla çalışır.
//
// GH_TOKEN: yalnızca bu depoya, yalnızca "Actions: Read and write" yetkili fine-grained anahtar.
// Cloudflare'de şifreli secret olarak durur (wrangler secret put GH_TOKEN); hiçbir yere yazılmaz.

const DEPO = "metinakdas/otoyol-ucretleri";
const IS_AKISI = "radar.yml";
const DAL = "main";

async function tetikle(env) {
  if (!env.GH_TOKEN) {
    console.error("GH_TOKEN tanımlı değil; tur başlatılmadı.");
    return;
  }
  const yanit = await fetch(
    `https://api.github.com/repos/${DEPO}/actions/workflows/${IS_AKISI}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tarife-radari-zamanlayici",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: DAL, inputs: { tetik: "zamanlayici" } }),
    },
  );
  if (yanit.status === 204) {
    console.log("Radar turu başlatıldı.");
    return;
  }
  // Yalnızca durum kodu ve GitHub'ın kısa hata iletisi yazılır; anahtar asla yazılmaz.
  let ileti = "";
  try {
    ileti = ((await yanit.json()).message || "").slice(0, 200);
  } catch (_) {
    // gövde JSON değil
  }
  throw new Error(`GitHub ${yanit.status}: ${ileti}`);
}

export default {
  async scheduled(_olay, env, ctx) {
    ctx.waitUntil(tetikle(env));
  },
};
