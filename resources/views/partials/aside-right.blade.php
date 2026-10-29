@php($user = auth()->user())

<aside id="sidebar-right" aria-label="Panel pengguna">
    <div class="sidebar-right-container">
        <div class="pane-header">
            <h3><i class="ti-user"></i> Panel Pengguna</h3>
            <button type="button" class="profile-panel-toggle panel-close" aria-label="Tutup panel pengguna">
                <i class="ti-close"></i>
            </button>
        </div>
        <div class="pane-body">
            <div class="text-center py-3">
                <span class="avatar-initial avatar-lg">{{ $user->initials }}</span>
                <h5 class="mt-3 mb-1">{{ $user->nama_lengkap }}</h5>
                <p class="text-secondary mb-2">{{ $user->email }}</p>
                <span class="badge badge-pill badge-soft-accent">{{ $user->role_label }}</span>
            </div>

            <div class="panel-section">
                <h6 class="panel-section-title">Tema Tampilan</h6>
                <div class="theme-options">
                    <button type="button" class="btn theme-option switch-theme" id="theme-default"
                        aria-pressed="false">
                        <span class="theme-dot theme-dot-light"></span> Light
                    </button>
                    <button type="button" class="btn theme-option switch-theme" id="theme-dark" aria-pressed="false">
                        <span class="theme-dot theme-dot-dark"></span> Dark
                    </button>
                    <button type="button" class="btn theme-option switch-theme" id="theme-blue" aria-pressed="false">
                        <span class="theme-dot theme-dot-blue"></span> Blue
                    </button>
                </div>
                <p class="text-secondary small mb-0 mt-2">Pilihan tema tersimpan di browser ini.</p>
            </div>

            <div class="panel-section">
                <h6 class="panel-section-title">Sesi</h6>
                <form method="POST" action="{{ route('logout') }}">
                    @csrf
                    <button type="submit" class="btn btn-outline-danger btn-sm btn-block">
                        <i class="ti-power-off"></i> Keluar dari akun
                    </button>
                </form>
            </div>
        </div>
    </div>
</aside>
