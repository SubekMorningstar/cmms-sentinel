<!DOCTYPE html>
<html lang="id">

<head>
    <meta charset="utf-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />

    <title>Masuk &middot; {{ config('app.name') }}</title>

    @include('partials.styles')
</head>

<body class="theme-dark">
    @include('partials.theme-init')

    <main class="login-wrapper">
        <div class="card login-card" id="login-card">
            <div class="card-body text-center login-head">
                <span class="login-mark"><i class="ti-pulse"></i></span>
                <h3 class="mb-1"><span class="text-carolina">CMMS</span></h3>
                <p class="text-secondary mb-0">Condition-Based Monitoring</p>
            </div>
            <div class="card-body login-body">
                <div class="text-center pb-4">
                    <h5 class="bold mb-1">Masuk ke Sistem</h5>
                    <p class="text-secondary small mb-0">Gunakan akun yang terdaftar untuk melanjutkan.</p>
                </div>

                <form method="POST" action="{{ route('login.store') }}" novalidate>
                    @csrf

                    <div class="form-group">
                        <label for="email">Email</label>
                        <div class="input-group">
                            <div class="input-group-prepend">
                                <span class="input-group-text"><i class="ti-email"></i></span>
                            </div>
                            <input type="email" name="email" id="email"
                                class="form-control @error('email') is-invalid @enderror"
                                value="{{ old('email') }}" placeholder="nama@perusahaan.com" required autofocus
                                autocomplete="username">
                        </div>
                        @error('email')
                            <div class="invalid-feedback d-block">{{ $message }}</div>
                        @enderror
                    </div>

                    <div class="form-group">
                        <label for="password">Password</label>
                        <div class="input-group">
                            <div class="input-group-prepend">
                                <span class="input-group-text"><i class="ti-lock"></i></span>
                            </div>
                            <input type="password" name="password" id="password"
                                class="form-control @error('password') is-invalid @enderror" placeholder="Password"
                                required autocomplete="current-password">
                        </div>
                        @error('password')
                            <div class="invalid-feedback d-block">{{ $message }}</div>
                        @enderror
                    </div>

                    <div class="form-checkbox mb-3">
                        <label>
                            <input type="checkbox" name="remember" {{ old('remember') ? 'checked' : '' }}>
                            <span class="checkmark"><i class="ti-check"></i></span>
                            Ingat saya
                        </label>
                    </div>

                    <button type="submit" class="btn btn-primary btn-block">Masuk</button>
                </form>
            </div>

            @if (app()->environment('local'))
                <div class="card-footer login-footer">
                    <p class="login-demo-label">Akun demo (lingkungan lokal)</p>
                    <div class="login-demo">
                        <p><code>admin@cmms.test</code> / <code>password</code><span>Administrator</span></p>
                        <p><code>teknisi@cmms.test</code> / <code>password</code><span>Teknisi</span></p>
                    </div>
                </div>
            @endif
        </div>
    </main>

    @include('partials.scripts')
</body>

</html>
