import {
  useEffect,
  useState,
  useRef,
  type FormEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { BookOpen, Eye, EyeOff, FileCheck2, MessageSquareText, ShieldCheck } from "lucide-react";
import { ui } from "@/lib/ui-text";

import { LiveWorkspace } from "./live-workspace";

type Navigate = (path: string) => void;

function PageLink({
  to,
  navigate,
  className,
  children,
}: {
  to: string;
  navigate: Navigate;
  className?: string;
  children: ReactNode;
}) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
      return;
    event.preventDefault();
    navigate(to);
  }
  return (
    <a href={to} className={className} onClick={follow}>
      {children}
    </a>
  );
}

function Brand({ navigate }: { navigate: Navigate }) {
  return (
    <PageLink to="/" navigate={navigate} className="brand">
      <ShieldCheck aria-hidden="true" size={24} /> {ui.brand}
    </PageLink>
  );
}

const featureIcons = [MessageSquareText, FileCheck2, BookOpen];

function Landing({ navigate }: { navigate: Navigate }) {
  return (
    <div className="platform landing">
      <header className="site-header">
        <Brand navigate={navigate} />
        <PageLink to="/signin" navigate={navigate} className="text-link">
          {ui.account.login}
        </PageLink>
      </header>
      <main>
        <section className="hero">
          <h1>
            {ui.landing.headline}
            <br /> {ui.landing.headlineEnd}
          </h1>
          <p>{ui.landing.intro}</p>
          <PageLink to="/workspace" navigate={navigate} className="product-button primary">
            {ui.landing.start}
          </PageLink>
        </section>
        <section className="feature-grid" aria-label={ui.landing.featuresLabel}>
          {ui.landing.features.map(({ title, text }, index) => {
            const Icon = featureIcons[index];
            return (
              <article className="feature-card" key={title}>
                <Icon size={22} aria-hidden="true" />
                <h2>{title}</h2>
                <p>{text}</p>
              </article>
            );
          })}
        </section>
      </main>
      <footer className="site-footer">
        <Brand navigate={navigate} />
        <span>{ui.landing.disclaimer}</span>
      </footer>
    </div>
  );
}

type AuthAction = "signin" | "signup" | "reset";

function AuthPage({ navigate, action }: { navigate: Navigate; action: AuthAction }) {
  const reset = action === "reset";
  const signIn = action === "signin";
  const copy = ui.account;
  const title = reset ? copy.reset : signIn ? copy.login : copy.register;
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [errors, setErrors] = useState<{ email?: string; password?: string; form?: string }>({});

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current) return;
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email") ?? "")
      .trim()
      .toLowerCase();
    const password = String(data.get("password") ?? "");
    const fields = {
      email:
        email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
          ? undefined
          : copy.invalidEmail,
      password:
        !signIn && (Array.from(password).length < 8 || Array.from(password).length > 128)
          ? copy.passwordLength
          : password
            ? undefined
            : copy.invalidPassword,
    };
    setErrors(fields);
    if (fields.email || fields.password) return;

    inFlight.current = true;
    setBusy(true);
    try {
      const response = await fetch(signIn ? "/api/auth/login" : "/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (response.ok) {
        navigate("/workspace");
        return;
      }
      const body = await response.json().catch(() => null);
      const form =
        response.status === 409 && body?.detail === "duplicate_email"
          ? copy.duplicate
          : response.status === 401 && body?.detail === "invalid_credentials"
            ? copy.credentials
            : response.status === 422
              ? copy.validation
              : copy.failure;
      setErrors({ form });
    } catch {
      setErrors({ form: copy.failure });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <main className="platform auth-layout">
      <section className="auth-card" aria-labelledby="auth-title">
        <Brand navigate={navigate} />
        <h1 id="auth-title">{title}</h1>
        {reset ? (
          <p>{copy.resetUnavailable}</p>
        ) : (
          <form onSubmit={submit} noValidate>
            <div className="auth-field">
              <label htmlFor="account-email">{copy.email}</label>
              <input
                id="account-email"
                name="email"
                type="email"
                autoComplete="email"
                autoFocus
                required
                aria-invalid={Boolean(errors.email)}
                aria-describedby={errors.email ? "email-error" : undefined}
              />
              {errors.email && (
                <span id="email-error" className="field-error">
                  {errors.email}
                </span>
              )}
            </div>
            {!reset && (
              <div className="auth-field">
                <label htmlFor="account-password">{copy.password}</label>
                <div className="password-field">
                  <input
                    id="account-password"
                    name="password"
                    type={visible ? "text" : "password"}
                    autoComplete={signIn ? "current-password" : "new-password"}
                    required
                    aria-invalid={Boolean(errors.password)}
                    aria-describedby={errors.password ? "password-error" : undefined}
                  />
                  <button
                    type="button"
                    className="icon-action"
                    aria-label={visible ? copy.hidePassword : copy.showPassword}
                    onClick={() => setVisible(!visible)}
                  >
                    {visible ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
                {errors.password && (
                  <span id="password-error" className="field-error">
                    {errors.password}
                  </span>
                )}
                {signIn && (
                  <PageLink to="/forgot-password" navigate={navigate} className="text-link">
                    {copy.forgot}
                  </PageLink>
                )}
              </div>
            )}
            {errors.form && (
              <p role="alert" className="field-error">
                {errors.form}
              </p>
            )}
            <button className="product-button primary" disabled={busy} type="submit">
              {busy ? copy.loading : title}
            </button>
          </form>
        )}
        <p className="auth-switch">
          {reset ? "" : `${signIn ? copy.newHere : copy.haveAccount} `}
          <PageLink to={signIn ? "/signup" : "/signin"} navigate={navigate} className="text-link">
            {signIn ? copy.register : copy.login}
          </PageLink>
        </p>
        <PageLink to="/workspace" navigate={navigate} className="text-link">
          {copy.guest}
        </PageLink>
      </section>
    </main>
  );
}

export function Platform() {
  const [location, setLocation] = useState(() => window.location.pathname + window.location.search);
  useEffect(() => {
    const handlePopState = () => setLocation(window.location.pathname + window.location.search);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);
  const navigate: Navigate = (path) => {
    window.history.pushState(null, "", path);
    setLocation(path);
    window.scrollTo(0, 0);
  };
  const path = location.split("?")[0];
  if (path === "/workspace" || path === "/dashboard") {
    return <LiveWorkspace key={location} onHome={() => navigate("/")} />;
  }
  if (path === "/signin" || path === "/signup" || path === "/forgot-password" || path === "/auth") {
    return (
      <AuthPage
        key={path}
        navigate={navigate}
        action={path === "/signup" ? "signup" : path === "/forgot-password" ? "reset" : "signin"}
      />
    );
  }
  return <Landing navigate={navigate} />;
}
