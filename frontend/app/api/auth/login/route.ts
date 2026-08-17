import { NextResponse } from "next/server";
import { callBackend } from "@/lib/backend";
import { setSessionCookies, type TokenPair } from "@/lib/session";

export async function POST(request: Request) {
  const body = await request.text();
  const upstream = await callBackend("/api/auth/login", {
    method: "POST",
    body,
  });
  const data = await upstream.json();

  if (!upstream.ok) {
    return NextResponse.json(data, { status: upstream.status });
  }

  const res = NextResponse.json({ ok: true });
  setSessionCookies(res, data as TokenPair);
  return res;
}
