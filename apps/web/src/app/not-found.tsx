import Link from "next/link";

export default function NotFound() {
  return (
    <main className="wrap notfound">
      <h2>Page not found</h2>
      <p>That page may have expired or never existed.</p>
      <Link className="btn btn-primary" href="/">
        Back to markets
      </Link>
    </main>
  );
}
