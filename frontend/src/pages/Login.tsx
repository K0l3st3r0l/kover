import { useState, FormEvent } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';

function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(email, password);
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 via-blue-950 to-slate-900 px-4">
      <div className="max-w-md w-full">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-blue-600 shadow-lg mb-4">
            <span className="text-white text-2xl font-bold">K</span>
          </div>
          <h1 className="text-3xl font-bold text-white">Kover</h1>
          <p className="text-blue-200/70 mt-1 text-sm">Gestión de portafolio de opciones</p>
        </div>
        <div className="bg-white/10 backdrop-blur border border-white/20 rounded-2xl shadow-2xl p-8">
          <h2 className="text-xl font-semibold text-white mb-6">Iniciar sesión</h2>

        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="bg-red-500/20 border border-red-400/40 text-red-200 p-3 rounded-lg text-sm mb-4">
              {error}
            </div>
          )}

          <div className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-blue-100 mb-1.5">
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-blue-200/50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent text-sm"
              placeholder="tu@email.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="block text-sm font-medium text-blue-100 mb-1.5">
              Contraseña
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full px-4 py-2.5 bg-white/10 border border-white/20 rounded-lg text-white placeholder-blue-200/50 focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent text-sm"
              placeholder="••••••••"
            />
          </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-6 btn-primary py-2.5 text-sm font-semibold disabled:opacity-50"
          >
            {loading ? 'Ingresando...' : 'Ingresar'}
          </button>
        </form>
        </div>
      </div>
    </div>
  );
}

export default Login;
