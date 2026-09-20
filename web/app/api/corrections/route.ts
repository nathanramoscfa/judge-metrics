// web/app/api/corrections/route.ts
// POST /api/corrections: the corrections form posts here, on the web
// server, which validates and forwards the allow-listed body to the API's
// POST /api/v1/corrections (lib/corrections-handler.ts). The browser never
// calls the API directly for a write: one origin, one validated shape, no
// cookie set, nothing logged. The response is the API's status with
// `{id, status}` or the error body.
import { handleCorrectionPost } from "@/lib/corrections-handler";

export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return handleCorrectionPost(request);
}
