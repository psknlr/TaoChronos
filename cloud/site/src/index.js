// The Worker behind https://chat.impf.ai: the site and its API (site.js).  Deployed by .github/workflows/site.yml.

import { handle } from "./site.js";

export default {
  fetch(request, env) {
    return handle(request, env, {
      // per visitor and Cloudflare location, over a minute (wrangler.toml: [[ratelimits]]); without the binding, no limit
      limit: async (kind, key) => {
        const binding = kind === "call" ? env.CALL_LIMIT : env.READ_LIMIT;
        if (!binding) return true;
        const { success } = await binding.limit({ key });
        return success;
      },
    });
  },
};
