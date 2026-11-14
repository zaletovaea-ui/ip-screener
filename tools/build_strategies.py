"""Собирает сайты стратегий из общего шаблона tools/strategy_template.html.
Запуск: python3 tools/build_strategies.py
Код страниц менять в шаблоне, параметры стратегий — здесь, затем пересобрать."""
import json, re, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
TPL = (ROOT / 'tools' / 'strategy_template.html').read_text(encoding='utf-8')

STRATEGIES = {
  'kupony': dict(
    key='kup', title='Акции на купоны', start='2024-07-26',
    strat=[['Дата начала ведения стратегии', '26 июля 2024 г.'], ['Риск-профиль', 'Консервативный'], ['Срок', 'от 3-х лет'],
           ['Коротко о стратегии', '', 'Первоначальный капитал 1&nbsp;млн руб., 100% в облигациях. По мере получения купонов реинвестирование их в акции. Новые вложения на счёт (при наличии у вас) вкладывать в облигации.']],
    sheets=dict(gk='Портфель для гк', tx='Текущий портфель', ref='Справочник по облигациям'),
    txMode='lots', bench=dict(code='MCFTR', name='индекс Мосбиржи полной доходности')),
  'profit': dict(
    key='prf', title='Купонный профит', start='2024-06-11',
    strat=[['Дата начала ведения стратегии', '11 июня 2024 г.'], ['Риск-профиль', 'Консервативный'], ['Срок', 'от 1 года'],
           ['Коротко о стратегии', '', 'Всепогодный портфель из облигаций в условиях неопределённости ДКП. Первоначальный капитал разделён на 5 частей по 20%: LQDT (фонд денежного рынка), облигации с плавающим купоном, облигации с привязкой к валюте, ОФЗ и корпоративные облигации с постоянным купоном. В зависимости от стадии рынка и денежно-кредитной политики (ДКП) ЦБ пропорции будут меняться.']],
    sheets=dict(gk='Портф для гк', tx='Сделки по портфелю', ref='Справочник облигаций в портфеле'),
    txMode='deals', bench=dict(code='RGBITR', name='индекс государственных облигаций полной доходности')),
}

for folder, cfg in STRATEGIES.items():
    block = '/*CFG-START*/\nconst CFG = ' + json.dumps(cfg, ensure_ascii=False, indent=1) + ';\n/*CFG-END*/'
    html = re.sub(r'/\*CFG-START\*/.*?/\*CFG-END\*/', lambda m: block, TPL, flags=re.S)
    html = html.replace('/*TITLE*/', cfg['title'])
    out = ROOT / 'docs' / folder / 'index.html'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')
    print('собран', out.relative_to(ROOT))
