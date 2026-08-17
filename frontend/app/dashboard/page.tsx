import { redirect } from "next/navigation";
import { callBackend } from "@/lib/backend";
import { getAccessToken } from "@/lib/session";

export default async function DashboardPage() {
  const token = await getAccessToken();
  if (!token) redirect("/login");

  const upstream = await callBackend("/api/auth/me", {
    headers: { authorization: `Bearer ${token}` },
  });
  if (!upstream.ok) redirect("/login");

  const user = (await upstream.json()) as { id: string; email: string };

  return (
    <main
      style={{ maxWidth: 560, margin: "80px auto", fontFamily: "system-ui" }}
    >
      <h1>Bạn đã đăng nhập</h1>
      <p>
        Tài khoản: <strong>{user.email}</strong>
      </p>
      <form action="/api/auth/logout" method="post">
        <button type="submit">Đăng xuất</button>
      </form>
    </main>
  );
}
