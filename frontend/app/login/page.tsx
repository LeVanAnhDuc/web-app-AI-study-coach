"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const form = new FormData(event.currentTarget);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        email: String(form.get("email")),
        password: String(form.get("password")),
      }),
    });

    if (res.ok) {
      router.push("/dashboard");
      router.refresh();
      return;
    }
    const data = await res.json().catch(() => ({}));
    setError(data.detail ?? "Đăng nhập không thành công. Thử lại nhé.");
    setBusy(false);
  }

  return (
    <main
      style={{ maxWidth: 380, margin: "80px auto", fontFamily: "system-ui" }}
    >
      <h1>Đăng nhập</h1>
      <form onSubmit={onSubmit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          required
          style={{ width: "100%" }}
        />
        <label htmlFor="password">Mật khẩu</label>
        <input
          id="password"
          name="password"
          type="password"
          required
          style={{ width: "100%" }}
        />
        {error && (
          <p role="alert" style={{ color: "#C8322E" }}>
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          {busy ? "Đang vào…" : "Đăng nhập"}
        </button>
      </form>
      <p>
        Chưa có tài khoản? <a href="/register">Tạo tài khoản</a>
      </p>
    </main>
  );
}
