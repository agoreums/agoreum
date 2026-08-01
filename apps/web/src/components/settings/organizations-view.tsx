"use client";

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import { truncateAddress } from "@/components/auth/connect-wallet";
import { useAuth } from "@/components/auth/auth-provider";
import {
  ApiError,
  orgsApi,
  type Organization,
  type OrgMember,
  type OrgRole,
} from "@/lib/api";

/**
 * Organizations and team management.
 *
 * A member sees the organizations they belong to and can create a team. Admins
 * and owners manage membership: invite by wallet address, change roles, and
 * remove people. Ownership is only ever granted or revoked by an owner, mirroring
 * exactly what the API permits, so the interface never offers an action that
 * would be refused.
 */
export function OrganizationsView() {
  const t = useTranslations("organizations");
  const { status, accessToken } = useAuth();

  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const refresh = useCallback(() => setReload((n) => n + 1), []);

  useEffect(() => {
    if (status !== "authenticated" || !accessToken) return;
    let cancelled = false;
    async function run() {
      try {
        const list = await orgsApi.list(accessToken!);
        if (cancelled) return;
        setOrgs(list);
        setSelected((prev) => prev ?? list.find((o) => o.kind === "team")?.slug ?? null);
        setError(null);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : t("loadFailed"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [status, accessToken, reload, t]);

  if (status !== "authenticated") {
    return (
      <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
        <p className="text-[var(--text-secondary)]">{t("signInRequired")}</p>
      </div>
    );
  }

  if (loading) {
    return <p className="text-[var(--text-muted)]">{t("loading")}</p>;
  }

  const active = orgs.find((o) => o.slug === selected) ?? null;

  return (
    <div className="space-y-10">
      {error ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4 text-sm text-danger-500">
          {error}
        </p>
      ) : null}

      <div className="grid gap-8 lg:grid-cols-[18rem_1fr]">
        <div className="space-y-4">
          <OrgList orgs={orgs} selected={selected} onSelect={setSelected} />
          <CreateOrg accessToken={accessToken!} onCreated={(slug) => {
            setSelected(slug);
            refresh();
          }} />
        </div>

        <div>
          {active ? (
            <OrgDetail
              key={active.slug}
              org={active}
              accessToken={accessToken!}
              onChanged={refresh}
            />
          ) : (
            <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-subtle)] p-10 text-center">
              <p className="text-[var(--text-secondary)]">{t("selectPrompt")}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function OrgList({
  orgs,
  selected,
  onSelect,
}: {
  orgs: Organization[];
  selected: string | null;
  onSelect: (slug: string) => void;
}) {
  const t = useTranslations("organizations");
  return (
    <nav className="overflow-hidden rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
      <p className="border-b border-[var(--border-subtle)] px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {t("yourOrgs")}
      </p>
      <ul>
        {orgs.map((org) => {
          const active = org.slug === selected;
          return (
            <li key={org.slug}>
              <button
                type="button"
                onClick={() => onSelect(org.slug)}
                aria-current={active ? "true" : undefined}
                className={`flex w-full items-center justify-between gap-2 px-4 py-3 text-start text-sm transition-colors ${
                  active
                    ? "bg-brand-500/10 text-[var(--text-primary)]"
                    : "text-[var(--text-secondary)] hover:bg-[var(--surface-raised)]"
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{org.name}</span>
                  <span className="mt-0.5 block truncate text-xs text-[var(--text-muted)]">
                    {org.kind === "personal" ? t("personal") : t("memberCount", { count: org.member_count })}
                  </span>
                </span>
                <RoleBadge role={org.role} />
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function CreateOrg({
  accessToken,
  onCreated,
}: {
  accessToken: string;
  onCreated: (slug: string) => void;
}) {
  const t = useTranslations("organizations");
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function submit() {
    if (!name.trim() || !slug.trim()) {
      setFormError(t("create.required"));
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      const org = await orgsApi.create(accessToken, {
        slug: slug.trim().toLowerCase(),
        name: name.trim(),
      });
      setSlug("");
      setName("");
      setOpen(false);
      onCreated(org.slug);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t("create.failed"));
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-xl border border-dashed border-[var(--border-subtle)] px-4 py-3 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:border-brand-500 hover:text-[var(--text-primary)]"
      >
        {t("create.cta")}
      </button>
    );
  }

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4">
      <h3 className="text-sm font-semibold">{t("create.title")}</h3>
      <div className="mt-3 space-y-3">
        <label className="block">
          <span className="text-xs font-medium text-[var(--text-secondary)]">{t("create.nameLabel")}</span>
          <input
            type="text"
            value={name}
            maxLength={96}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 block w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-3 py-2 text-sm outline-none focus:border-brand-500"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-[var(--text-secondary)]">{t("create.slugLabel")}</span>
          <input
            type="text"
            value={slug}
            maxLength={64}
            onChange={(e) => setSlug(e.target.value)}
            placeholder={t("create.slugPlaceholder")}
            className="mt-1 block w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-3 py-2 font-mono text-sm outline-none focus:border-brand-500"
          />
        </label>
        {formError ? <p className="text-xs text-danger-500">{formError}</p> : null}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
          >
            {busy ? t("create.creating") : t("create.submit")}
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-xl border border-[var(--border-subtle)] px-4 py-2 text-sm font-medium transition-colors hover:border-[var(--border-strong)]"
          >
            {t("create.cancel")}
          </button>
        </div>
      </div>
    </section>
  );
}

function OrgDetail({
  org,
  accessToken,
  onChanged,
}: {
  org: Organization;
  accessToken: string;
  onChanged: () => void;
}) {
  const t = useTranslations("organizations");
  const { user } = useAuth();
  const [members, setMembers] = useState<OrgMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const refresh = useCallback(() => setReload((n) => n + 1), []);

  const canManage = org.role === "admin" || org.role === "owner";
  const isPersonal = org.kind === "personal";

  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        const list = await orgsApi.members(accessToken, org.slug);
        if (!cancelled) {
          setMembers(list);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : t("membersFailed"));
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, [accessToken, org.slug, reload, t]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[length:var(--text-h3)] font-semibold tracking-[var(--text-h3--letter-spacing)]">
            {org.name}
          </h2>
          <p className="mt-1 font-mono text-xs text-[var(--text-muted)]">{org.slug}</p>
        </div>
        <RoleBadge role={org.role} />
      </div>

      {isPersonal ? (
        <p className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] bg-[var(--surface-raised)] p-4 text-sm text-[var(--text-secondary)]">
          {t("personalHint")}
        </p>
      ) : null}

      {!isPersonal && canManage ? (
        <AddMember accessToken={accessToken} slug={org.slug} onAdded={refresh} />
      ) : null}

      {error ? <p className="text-sm text-danger-500">{error}</p> : null}

      {members === null ? (
        <p className="text-sm text-[var(--text-muted)]">{t("loadingMembers")}</p>
      ) : (
        <MemberList
          members={members}
          org={org}
          currentUserId={user?.id ?? null}
          accessToken={accessToken}
          onChanged={() => {
            refresh();
            onChanged();
          }}
        />
      )}
    </div>
  );
}

function AddMember({
  accessToken,
  slug,
  onAdded,
}: {
  accessToken: string;
  slug: string;
  onAdded: () => void;
}) {
  const t = useTranslations("organizations");
  const [address, setAddress] = useState("");
  const [role, setRole] = useState<OrgRole>("member");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function submit() {
    if (!address.trim()) {
      setFormError(t("add.required"));
      return;
    }
    setBusy(true);
    setFormError(null);
    try {
      await orgsApi.addMember(accessToken, slug, {
        address: address.trim().toLowerCase(),
        role,
      });
      setAddress("");
      setRole("member");
      onAdded();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t("add.failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-[var(--radius-card)] border border-[var(--border-subtle)] p-4">
      <h3 className="text-sm font-semibold">{t("add.title")}</h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">{t("add.hint")}</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="0x…"
          className="min-w-0 flex-1 rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-3 py-2 font-mono text-sm outline-none focus:border-brand-500"
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as OrgRole)}
          className="rounded-xl border border-[var(--border-subtle)] bg-[var(--surface-base)] px-3 py-2 text-sm outline-none focus:border-brand-500"
        >
          <option value="member">{t("roles.member")}</option>
          <option value="admin">{t("roles.admin")}</option>
        </select>
        <button
          type="button"
          onClick={submit}
          disabled={busy}
          className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-500 disabled:opacity-60"
        >
          {busy ? t("add.adding") : t("add.submit")}
        </button>
      </div>
      {formError ? <p className="mt-2 text-xs text-danger-500">{formError}</p> : null}
    </section>
  );
}

function MemberList({
  members,
  org,
  currentUserId,
  accessToken,
  onChanged,
}: {
  members: OrgMember[];
  org: Organization;
  currentUserId: string | null;
  accessToken: string;
  onChanged: () => void;
}) {
  const t = useTranslations("organizations");
  const canManage = org.role === "admin" || org.role === "owner";
  const isOwner = org.role === "owner";

  async function setRole(userId: string, role: OrgRole) {
    try {
      await orgsApi.updateMember(accessToken, org.slug, userId, role);
      onChanged();
    } catch {
      onChanged();
    }
  }

  async function remove(userId: string) {
    if (!window.confirm(t("member.removeConfirm"))) return;
    try {
      await orgsApi.removeMember(accessToken, org.slug, userId);
      onChanged();
    } catch {
      onChanged();
    }
  }

  async function leave() {
    if (!window.confirm(t("member.leaveConfirm"))) return;
    try {
      await orgsApi.leave(accessToken, org.slug);
      onChanged();
    } catch {
      onChanged();
    }
  }

  return (
    <section>
      <h3 className="text-sm font-semibold">{t("membersTitle")}</h3>
      <ul className="mt-3 divide-y divide-[var(--border-subtle)] rounded-[var(--radius-card)] border border-[var(--border-subtle)]">
        {members.map((m) => {
          const isSelf = m.user_id === currentUserId;
          const name = m.display_name || m.username || truncateAddress(m.primary_address);
          // Owner-only actions on owners; admins manage members/admins but never owners.
          const editable =
            canManage && !isSelf && (m.role === "owner" ? isOwner : true);
          return (
            <li
              key={m.user_id}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {name}
                  {isSelf ? (
                    <span className="ms-2 text-xs text-[var(--text-muted)]">{t("member.you")}</span>
                  ) : null}
                </p>
                <p className="mt-0.5 truncate font-mono text-xs text-[var(--text-muted)]">
                  {truncateAddress(m.primary_address)}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {editable && org.kind === "team" ? (
                  <select
                    value={m.role}
                    onChange={(e) => setRole(m.user_id, e.target.value as OrgRole)}
                    className="rounded-lg border border-[var(--border-subtle)] bg-[var(--surface-base)] px-2 py-1 text-xs outline-none focus:border-brand-500"
                  >
                    <option value="member">{t("roles.member")}</option>
                    <option value="admin">{t("roles.admin")}</option>
                    {isOwner ? <option value="owner">{t("roles.owner")}</option> : null}
                  </select>
                ) : (
                  <RoleBadge role={m.role} />
                )}
                {editable && org.kind === "team" ? (
                  <button
                    type="button"
                    onClick={() => remove(m.user_id)}
                    className="rounded-lg border border-[var(--border-subtle)] px-2.5 py-1 text-xs font-medium text-danger-500 transition-colors hover:border-danger-500"
                  >
                    {t("member.remove")}
                  </button>
                ) : null}
                {isSelf && org.kind === "team" ? (
                  <button
                    type="button"
                    onClick={leave}
                    className="rounded-lg border border-[var(--border-subtle)] px-2.5 py-1 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:border-danger-500 hover:text-danger-500"
                  >
                    {t("member.leave")}
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function RoleBadge({ role }: { role: OrgRole }) {
  const t = useTranslations("organizations");
  const tone =
    role === "owner"
      ? "text-brand-500 border-brand-500/40"
      : role === "admin"
        ? "text-[var(--text-primary)] border-[var(--border-strong)]"
        : "text-[var(--text-muted)] border-[var(--border-subtle)]";
  return (
    <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${tone}`}>
      {t(`roles.${role}`)}
    </span>
  );
}
