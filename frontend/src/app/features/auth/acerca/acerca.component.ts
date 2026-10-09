import { Component }    from '@angular/core';
import { RouterLink }   from '@angular/router';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-acerca',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <!-- Navbar pública -->
    <nav class="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
      <div class="flex items-center gap-6">
        <img src="assets/logo.jpeg" alt="ApuGuard" class="h-8 w-auto object-contain">
        <a href="#" class="text-sm text-gray-600 hover:text-primary">Acerca del Proyecto</a>
        <a routerLink="/dashboard" class="text-sm text-gray-600 hover:text-primary">Dashboard</a>
      </div>
      <a routerLink="/login" class="btn-primary text-sm">Iniciar Sesión</a>
    </nav>

    <!-- Hero -->
    <div class="max-w-4xl mx-auto px-6 py-16">

      <div class="card mb-6 text-center">
        <div class="inline-flex items-center gap-2 bg-blue-50 text-blue-700 px-3 py-1 rounded-full text-xs font-semibold mb-4">
          <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
          </svg>
          Contexto del Sistema
        </div>
        <h1 class="text-2xl font-bold text-gray-800 mb-2">
          Plataforma de prevención de Deforestación - Prueba de cambios sss
        </h1>
        <p class="text-gray-500 text-sm">
          Basada en imágenes satelitales Sentinel-2 y modelos de aprendizaje profundo
        </p>
      </div>

      <div class="card mb-6">
        <div class="flex items-start gap-3">
          <svg class="w-5 h-5 text-blue-500 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/>
          </svg>
          <div>
            <h3 class="font-semibold text-gray-800 mb-2">La deforestación amazónica es un problema crítico</h3>
            <p class="text-sm text-gray-600 leading-relaxed">
              La Amazonía peruana, una de las regiones con mayor biodiversidad del planeta, enfrenta un
              aumento constante de la deforestación debido a actividades como la expansión agrícola,
              la minería ilegal y el crecimiento de infraestructura no planificada.
            </p>
            <p class="text-sm text-gray-500 mt-2 leading-relaxed">
              Este fenómeno no solo reduce drásticamente la cobertura forestal, sino que también
              fragmenta hábitats, incrementa las emisiones de carbono y acelera el cambio climático global.
            </p>
            <p class="text-sm text-gray-400 mt-2 italic">
              A pesar de los esfuerzos de conservación, la detección oportuna de estos eventos sigue siendo
              un desafío debido a la gran extensión del territorio y la limitada capacidad de monitoreo en tiempo real.
            </p>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        <div class="card">
          <div class="aspect-video bg-primary/10 rounded-lg flex items-center justify-center mb-3">
            <span class="text-primary text-sm font-medium">Mapa Reserva Tambopata</span>
          </div>
          <h3 class="font-semibold text-gray-800 mb-2">Arquitectura del Sistema</h3>
          <div class="space-y-2 text-sm text-gray-600">
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 bg-blue-500 rounded-full"></span>
              <span><strong>Fuente de Datos:</strong> Sentinel-2 L2A (10m resolución)</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 bg-green-500 rounded-full"></span>
              <span><strong>Modelo IA:</strong> HRNet segmentación semántica</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 bg-purple-500 rounded-full"></span>
              <span><strong>Infraestructura:</strong> AWS SageMaker + S3</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="w-2 h-2 bg-orange-500 rounded-full"></span>
              <span><strong>Alertas:</strong> SMS automático vía Twilio</span>
            </div>
          </div>
        </div>
        <div class="card">
          <h3 class="font-semibold text-gray-800 mb-3">Área de Cobertura</h3>
          <div class="space-y-2 text-sm text-gray-600">
            <p>Reserva Nacional de Tambopata, Madre de Dios, Perú</p>
            <p class="text-gray-500">Coordenadas: 12°S — 70°W aprox.</p>
            <p class="text-gray-500">Área monitorizada: ~274,690 ha</p>
            <p class="text-gray-500">Frecuencia de análisis: quincenal (Sentinel-2)</p>
          </div>
        </div>
      </div>

      <div class="text-center">
        <a routerLink="/login" class="btn-primary inline-block">
          Ingresar al Sistema →
        </a>
      </div>
    </div>
  `
})
export class AcercaComponent {}
