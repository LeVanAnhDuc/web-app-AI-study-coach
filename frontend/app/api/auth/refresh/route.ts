import { NextResponse } from "next/server";
import { callBackend } from "@/lib/backend";
import {
  clearSessionCookies,
  getRefreshToken,
  setSessionCookies,
  type TokenPair,
} from "@/lib/session";

export async function POST() {
  const refreshToken = await getRefreshToken();
  if (!refreshToken) {
    return NextResponse.json(
      { detail: "Không có phiên đăng nhập." },
      { status: 401 },
    );
  }

  const upstream = await callBackend("/api/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const data = await upstream.json();

  if (!upstream.ok) {
    const res = NextResponse.json(data, { status: upstream.status });
    clearSessionCookies(res);
    return res;
  }

  const res = NextResponse.json({ ok: true });
  setSessionCookies(res, data as TokenPair);
  return res;
}
