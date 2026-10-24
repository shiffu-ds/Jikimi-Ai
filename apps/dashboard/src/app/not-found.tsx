import Link from "next/link";

export default function NotFound() {
  return (
    <div className="grid min-h-screen place-items-center px-4 text-center">
      <div>
        <p className="font-mono text-6xl font-black text-brand-500">404</p>
        <p className="mt-2 text-slate-500">صفحہ نہیں ملا · Page not found</p>
        <Link href="/" className="btn-primary mt-6">
          Jikimi AI
        </Link>
      </div>
    </div>
  );
}
