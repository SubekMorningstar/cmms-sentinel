<!DOCTYPE html>
<html lang="id">

<head>
    <meta charset="utf-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />

    <title>Akses Ditolak &middot; {{ config('app.name') }}</title>

    @include('partials.styles')
</head>

<body class="theme-dark">
    @include('partials.theme-init')

    <main class="login-wrapper error-wrapper">
        <div class="card login-card error-card">
            <div class="card-body text-center">
                <span class="error-mark"><i class="ti-lock"></i></span>
                <p class="error-code">403</p>
                <h4 class="mb-2">Akses ditolak</h4>
                <p class="text-secondary mb-4">
                    Akun Anda tidak memiliki izin untuk membuka halaman ini. Hubungi administrator bila Anda merasa
                    seharusnya memiliki akses.
                </p>

                @auth
                    <a href="{{ route('dashboard') }}" class="btn btn-primary btn-block">
                        <i class="ti-arrow-left"></i> Kembali ke Dashboard
                    </a>
                @else
                    <a href="{{ route('login') }}" class="btn btn-primary btn-block">
                        <i class="ti-arrow-left"></i> Kembali ke Halaman Masuk
                    </a>
                @endauth
            </div>
        </div>
    </main>

    @include('partials.scripts')
</body>

</html>
