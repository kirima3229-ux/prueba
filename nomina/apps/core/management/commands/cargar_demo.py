"""Datos de demostración (ficticios) para probar el sistema en una computadora. No funciona en producción."""

import io
from datetime import date, timedelta
from decimal import Decimal as D

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from PIL import Image, ImageDraw

from apps.companias.logo import procesar
from apps.companias.models import ClasificacionCFSE, Compania, Departamento, LogoCompania, TasaCFSE, TasasCompania
from apps.cuentas.models import Usuario
from apps.empleados.models import Empleado
from apps.licencias import servicios as licencias
from apps.nomina import cheques, servicios
from apps.nomina.models import DeduccionRecurrente, EntradaIngreso
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso
from apps.servicios import pagos
from apps.servicios.models import ProveedorServicios


class Command(BaseCommand):
    help = ("Crea la compañía ficticia «Restaurante La Ceiba, LLC» con 6 empleados, 3 nóminas cerradas, una "
            "pre-nómina, cheques y un proveedor de servicios. Sólo para probar; no funciona en producción.")

    def handle(self, *args, **opciones):
        if settings.PRODUCCION:
            raise CommandError("Los datos de demostración no se cargan en producción.")
        if Compania.objects.filter(nombre="Restaurante La Ceiba, LLC").exists():
            raise CommandError("Los datos de demostración ya están cargados.")
        admin = (Usuario.objects.filter(Q(is_superuser=True) | Q(rol=Usuario.Rol.ADMIN), is_active=True)
                 .order_by("id").first())
        if admin is None:
            raise CommandError("Primero cree el administrador: python manage.py createsuperuser")
        with transaction.atomic():
            self._cargar(admin)
        self.stdout.write(self.style.SUCCESS(
            "Datos de demostración cargados: Restaurante La Ceiba, LLC (6 empleados, 4 nóminas). "
            "Todos los datos son ficticios."))

    def _cargar(self, admin):
        c = Compania(nombre="Restaurante La Ceiba, LLC", frecuencia_pago="semanal", numero_empleados=12,
                     direccion_linea1="Calle Loíza 1850", ciudad="San Juan", estado="PR", codigo_postal="00911")
        c.asignar_ein("661234567")
        c.cuenta_patronal_dtrh = "0123456789"
        c.save()
        TasasCompania.objects.create(compania=c, anio=2026, suta_tasa=D("2.4"), aportacion_especial_tasa=D("1"),
                                     sinot_empleado_tasa=D("0.3"), sinot_patrono_tasa=D("0.3"))
        cocina, salon, adm = (Departamento.objects.create(compania=c, nombre=n) for n in ("Cocina", "Salón", "Administración"))
        rest = ClasificacionCFSE.objects.create(compania=c, codigo="9079", descripcion="Restaurantes")
        ofi = ClasificacionCFSE.objects.create(compania=c, codigo="8810", descripcion="Oficina")
        TasaCFSE.objects.create(clasificacion=rest, anio=2026, tasa_por_100=D("2.50"))
        TasaCFSE.objects.create(clasificacion=ofi, anio=2026, tasa_por_100=D("0.30"))

        # Logo de ejemplo
        im = Image.new("RGBA", (600, 200), (255, 255, 255, 0))
        d = ImageDraw.Draw(im)
        d.ellipse((10, 20, 170, 180), fill=(31, 122, 77, 255))
        d.rectangle((80, 110, 100, 190), fill=(120, 72, 30, 255))
        d.rounded_rectangle((200, 70, 590, 130), 20, fill=(15, 76, 129, 255))
        b = io.BytesIO()
        im.save(b, "PNG")
        datos, ancho, alto = procesar(SimpleUploadedFile("logo.png", b.getvalue()))
        LogoCompania.objects.create(compania=c, imagen=datos, ancho=ancho, alto=alto, actualizado_por=admin)


        def empleado(numero, ssn, nombre, paterno, materno, depto, cfse, **extra):
            e = Empleado(compania=c, numero_empleado=numero, nombre=nombre, apellido_paterno=paterno,
                         apellido_materno=materno, departamento=depto, clasificacion_cfse=cfse,
                         direccion_linea1=extra.pop("dir", "Calle Principal 12"), ciudad=extra.pop("ciudad", "San Juan"),
                         estado="PR", codigo_postal="00911", **extra)
            e.asignar_ssn(ssn)
            e.save()
            return e


        carmen = empleado("101", "581234567", "Carmen", "Rivera", "Ortiz", cocina, rest, fecha_empleo=date(2015, 3, 5),
                          tipo_pago="hora", tarifa=D("12.50"))
        jose = empleado("102", "582345678", "José", "Santiago", "Colón", salon, rest, fecha_empleo=date(2021, 6, 14),
                        tipo_pago="hora", tarifa=D("2.13"), recibe_propinas=True)
        maria = empleado("103", "583456789", "María", "López", "Vega", adm, ofi, fecha_empleo=date(2019, 1, 7),
                         tipo_pago="salario", tarifa=D("1100"), horas_regulares_periodo=D("40"), deposito_directo=True,
                         banco_nombre="Banco Popular", banco_ruta="021502011", r4_estado_civil="casado", r4_dependientes=2)
        maria.asignar_cuenta_bancaria("004512349876")
        maria.save()
        luis = empleado("104", "584567890", "Luis", "Torres", "Cruz", cocina, rest, fecha_empleo=date(2022, 9, 1),
                        tipo_pago="hora", tarifa=D("15"), aplica_choferil=True, dir="Calle 5 #22", ciudad="Carolina")
        ana = empleado("105", "585678901", "Ana", "Méndez", "Soto", salon, rest, fecha_empleo=date(2024, 2, 19),
                       tipo_pago="hora", tarifa=D("11"), recibe_propinas=True)
        pedro = empleado("106", "586789012", "Pedro", "Ramírez", "Díaz", adm, ofi, fecha_empleo=date(2025, 11, 3),
                         tipo_pago="hora", tarifa=D("22"), w4_aplica=True, w4_estado_civil="married",
                         dir="200 Brickell Ave", ciudad="Miami")

        plan = ConceptoDeduccion.objects.get(codigo="plan_medico")
        k401 = ConceptoDeduccion.objects.get(codigo="retiro_401k")
        DeduccionRecurrente.objects.create(empleado=maria, concepto=plan, monto=D("45"))
        DeduccionRecurrente.objects.create(empleado=pedro, concepto=k401, monto=D("60"))

        for e, vac, enf in ((carmen, 96, 40), (jose, 44, 24), (maria, 120, 56), (luis, 32, 16), (ana, 12, 8), (pedro, 0, 0)):
            for tipo, horas in (("vacaciones", vac), ("enfermedad", enf)):
                if horas:
                    licencias.registrar_movimiento(empleado=e, tipo=tipo, clase="saldo_inicial", horas=D(horas),
                                                   fecha=date(2026, 1, 1), descripcion="Saldo al comenzar el sistema",
                                                   usuario=admin)

        propinas = ConceptoIngreso.objects.get(codigo="propinas")
        HORAS = {
            carmen: dict(horas_regulares="40", horas_extra_semanales="4"),
            jose: dict(horas_regulares="36"),
            maria: {},
            luis: dict(horas_regulares="40", horas_extra_diarias="2"),
            ana: dict(horas_regulares="30"),
            pedro: dict(horas_regulares="40"),
        }
        periodos = []
        for semana, inicio in enumerate((date(2026, 8, 31), date(2026, 9, 7), date(2026, 9, 14), date(2026, 9, 21))):
            p = servicios.crear_periodo(compania=c, inicio=inicio, fin=inicio + timedelta(days=6),
                                        fecha_pago=inicio + timedelta(days=11), usuario=admin)
            for emp, horas in HORAS.items():
                entrada = p.entradas.get(empleado=emp)
                for campo, valor in horas.items():
                    setattr(entrada, campo, D(valor))
                if emp is carmen and semana == 2:
                    entrada.horas_vacaciones = D("8")
                    entrada.horas_regulares = D("32")
                entrada.save()
                if emp in (jose, ana):
                    EntradaIngreso.objects.create(entrada=entrada, concepto=propinas, monto=D("310") if emp is jose else D("245"))
            servicios.marcar_modificado(p)
            errores = servicios.calcular_periodo(p, admin)
            if errores:
                raise CommandError("; ".join(errores))
            if semana < 3:
                servicios.cerrar_periodo(p, admin)
            periodos.append(p)

        emitir = [r for r in periodos[2].resultados.all() if cheques.por_cheque_sugerido(r)]
        cheques.emitir(periodos[2], emitir, 4518, admin)

        prov = ProveedorServicios(compania=c, numero="P-001", tipo_persona="entidad", nombre="Contabilidad Pérez, CSP")
        prov.asignar_identificacion("ein", "660987654")
        prov.save()
        for fecha, monto in ((date(2026, 7, 10), "400"), (date(2026, 8, 10), "650"), (date(2026, 9, 10), "650")):
            pagos.registrar(proveedor=prov, fecha=fecha, monto=D(monto), usuario=admin, referencia=f"F-{fecha:%m%y}")
