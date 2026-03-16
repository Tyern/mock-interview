'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || '/api';

export default function CandidatePage() {
  const router = useRouter();

  const [name, setName] = useState('');
  const [department, setDepartment] = useState('');
  const [institution, setInstitution] = useState('');

  const [userId, setUserId] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

  async function createCandidate() {
    const res = await fetch(`${API_BASE_URL}/new_candidate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        department,
        institution_name: institution,
      }),
    });

    const data = await res.json();
    setUserId(data.user_id);
  }

  async function uploadCV() {
    if (!file || !userId) return;

    const form = new FormData();
    form.append('user_id', userId);
    form.append('file', file);

    await fetch(`${API_BASE_URL}/upload_cv`, {
      method: 'POST',
      body: form,
    });

    router.push(`/interview?user_id=${userId}`);
  }

  return (
    <div style={{ padding: 40 }}>
      <h1>Candidate Registration</h1>

      <div>
        <input
          placeholder="Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>

      <div>
        <input
          placeholder="Department"
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
        />
      </div>

      <div>
        <input
          placeholder="Institution Name"
          value={institution}
          onChange={(e) => setInstitution(e.target.value)}
        />
      </div>

      <button onClick={createCandidate}>Save Candidate</button>

      {userId && (
        <>
          <h3>Upload CV</h3>

          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />

          <button onClick={uploadCV}>Upload CV</button>
        </>
      )}
    </div>
  );
}