"use client";

import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, notificationsApi, type NotificationItem } from "@/lib/api";

/**
 * The notification inbox.
 *
 * Every row is a real notification the platform raised: an order event, a
 * verification result, a team change. Unread items are marked as they are opened
 * or cleared in one action; nothing is fabricated to fill the list.
 */
export function NotificationsView() {
  const t = useTranslations("notifications");
  const { status, accessToken } = useAuth();

  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [unread, setUnread] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const refresh = () => setReload((n) => n + 1);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const list = await notificationsApi.list(accessToken!);
        if (cancelled) return;
        setItems(list.items);
        setUnread(list.unread);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("loadFailed"));
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, reload, t]);

  async function markAll() {
    if (!accessToken) return;
    try {
      await notificationsApi.markAllRead(accessToken);
    } finally {
      refresh();
    }
  }

  async function markOne(id: string) {
    if (!accessToken) return;
    try {
      await notificationsApi.markRead(accessToken, id);
    } finally {
      refresh();
    }
  }

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  if (items === null && !error) {
    return <NotificationsSkeleton />;
  }

  return (
    <div className="space-y-5">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-[var(--text-secondary)]">
          {unread > 0 ? t("unreadCount", { count: unread }) : t("allRead")}
        </p>
        {unread > 0 ? (
          <button
            type="button"
            onClick={markAll}
            className="rounded-xl border border-[var(--border-subtle)] px-4 py-2 text-sm font-medium transition-colors hover:border-brand-500"
          >
            {t("markAllRead")}
          </button>
        ) : null}
      </div>

      {items && items.length === 0 ? (
        <p className="rounded-[var(--radius-card)] border border-dashed border-[var(--border-subtle)] p-10 text-center text-sm text-[var(--text-muted)]">
          {t("empty")}
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
          {items?.map((n) => {
            const isUnread = n.read_at === null;
            return (
              <li
                key={n.id}
                className={`flex items-start gap-3 px-5 py-4 ${
                  isUnread ? "bg-brand-500/5" : ""
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`mt-1.5 size-2 shrink-0 rounded-full ${
                    isUnread ? "bg-brand-500" : "bg-transparent"
                  }`}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-[var(--text-primary)]">
                    {n.title}
                  </p>
                  {n.body ? (
                    <p className="mt-0.5 text-sm text-[var(--text-secondary)]">
                      {n.body}
                    </p>
                  ) : null}
                  <p className="mt-1 text-xs text-[var(--text-muted)]">
                    {new Date(n.created_at).toLocaleString()}
                  </p>
                </div>
                {isUnread ? (
                  <button
                    type="button"
                    onClick={() => markOne(n.id)}
                    className="shrink-0 rounded-lg border border-[var(--border-subtle)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:border-brand-500 hover:text-[var(--text-primary)]"
                  >
                    {t("markRead")}
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function NotificationsSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="h-16 animate-pulse rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)]"
        />
      ))}
    </div>
  );
}
