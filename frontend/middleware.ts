import { NextResponse, type NextRequest } from "next/server";
import { requestBodyHeaderStatus } from "@/lib/request-limits";

export function middleware(request: NextRequest) {
  if (["POST", "PUT", "PATCH"].includes(request.method)) {
    const status = requestBodyHeaderStatus(request.headers.get("content-length"));
    if (status) {
      return NextResponse.json({ error: {
        code: status === 413 ? "request_too_large" : "invalid_content_length",
        message: status === 413 ? "Request body exceeds 1 MiB." : "Invalid request body length.",
        trace_id: request.headers.get("x-request-id") ?? "unknown", details: null,
      } }, { status });
    }
  }
  return NextResponse.next();
}

export const config = { matcher: "/api/v1/:path*" };
