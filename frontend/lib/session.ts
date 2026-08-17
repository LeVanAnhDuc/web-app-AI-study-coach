import { cookies } from "next/headers";
import type { NextResponse } from "next/server";

export const ACCESS_COOKIE = "sc_access";
export const REFRESH_COOKIE = "sc_refresh";

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

const BASE = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export function setSessionCookies(res: NextResponse, tokens: TokenPair): void {
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    ...BASE,
    maxAge: tokens.expires_in,
  });
  res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    ...BASE,
    maxAge: 60 * 60 * 24 * 30,
  });
}

export function clearSessionCookies(res: NextResponse): void {
  res.cookies.delete(ACCESS_COOKIE);
  res.cookies.delete(REFRESH_COOKIE);
}

export async function getAccessToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(ACCESS_COOKIE)?.value;
}

export async function getRefreshToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(REFRESH_COOKIE)?.value;
}
