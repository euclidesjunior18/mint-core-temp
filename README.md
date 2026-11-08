# Mint Core Temp 🌡️

Monitor de temperatura do processador para **Linux Mint** (Cinnamon, MATE e XFCE), inspirado no clássico **Core Temp** do Windows.

O aplicativo exibe a temperatura atual da CPU diretamente na barra de tarefas / bandeja do sistema (ao lado do relógio), com suporte a minimização, alertas térmicos e estatísticas em tempo real.

![Mint Core Temp](icon.png)

---

## 🚀 Principais Funcionalidades

1. **Ícone Dinâmico na Bandeja (junto ao relógio)**:
   - Exibe o número da temperatura em tempo real no ícone e/ou no rótulo de texto (ex: ` 45°C `).
   - Cores intuitivas:
     - 🟢 **Verde** (< 55°C): Temperatura normal e segura.
     - 🟠 **Laranja** (55°C a 72°C): Em carga / aquecimento moderado.
     - 🔴 **Vermelho** (> 72°C): Temperatura alta / crítica.
2. **Minimizar para a Bandeja**:
   - Ao fechar a janela no botão `X`, o aplicativo continua rodando discretamente ao lado do relógio.
   - Um clique na opção da bandeja abre a janela novamente instantaneamente.
3. **Painel de Informações Estilo Core Temp**:
   - Modelo do processador, arquitetura e contagem de núcleos (físicos e lógicos).
   - Clock atual (frequência em MHz).
   - Temperatura atual em destaque com mostrador visual.
   - Histórico de temperaturas **Mínima**, **Média** e **Máxima**, com botão para resetar.
   - Gráfico de temperatura em tempo real (últimos 60 segundos).
   - Uso da CPU geral e medidores individuais para cada núcleo.
4. **Configurações Personalizáveis**:
   - Escolha do sensor de monitoramento (detecção automática ou seleção manual).
   - Ajuste de calibração (*offset* em °C).
   - Intervalo de atualização ajustável (1s, 1.5s, 2s, 3s, 5s).
   - Estilo na bandeja: *Ícone com número + Texto*, *Apenas Ícone* ou *Apenas Texto*.
   - Alerta configurável com notificação nativa do Linux Mint se a temperatura passar do limite (ex: 80°C).
   - Opção para **Iniciar automaticamente junto com o Linux Mint**.
   - Opção para iniciar já minimizado na bandeja.

---

## 📦 Como Usar

### 1. Iniciar pelo Menu de Aplicativos
Basta abrir o menu do Linux Mint e pesquisar por **Mint Core Temp** ou **Temperatura**.

### 2. Iniciar pelo Terminal
Para abrir a janela do programa:
```bash
/home/junior/Documentos/monitor_temp/core_temp.py
```

Para iniciar direto minimizado na bandeja do sistema:
```bash
/home/junior/Documentos/monitor_temp/core_temp.py --minimized
```

---

## 🛠️ Reinstalação e Desinstalação

Se você mover a pasta ou desejar atualizar o atalho no sistema:
```bash
./install.sh
```

Para desinstalar os atalhos e inicialização automática:
```bash
./uninstall.sh
```

---

## ⚙️ Dependências do Sistema

O aplicativo usa bibliotecas nativas já presentes no Linux Mint:
- Python 3
- PyGObject (`Gtk 3.0`, `AyatanaAppIndicator3`, `Notify`)
- `python3-psutil`
- `python3-cairo`
