<template>
	<div>
		<div v-if="doc" class="overflow-x-auto">
			<table class="text w-full text-sm">
				<thead>
					<tr class="text-gray-600">
						<th class="border-b py-3 pr-2 text-left font-normal">
							Description
						</th>
						<th class="border-b py-3 pr-2 text-left font-normal">Site</th>
						<th
							class="whitespace-nowrap border-b py-3 pr-2 text-right font-normal"
						>
							Rate
						</th>
						<th class="border-b py-3 pr-2 text-right font-normal">Amount</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="(row, i) in doc.items" :key="row.idx">
						<td class="border-b py-3 pr-2">
							{{ row.description || row.document_name }}
						</td>
						<td class="border-b py-3 pr-2">
							{{ row.site || '-' }}
						</td>
						<td class="border-b py-3 pr-2 text-right">
							{{ row.rate }} x {{ row.quantity }}
						</td>
						<td class="border-b py-3 pr-2 text-right font-semibold">
							{{ doc.formatted.items[i].amount }}
						</td>
					</tr>
				</tbody>
				<tfoot>
					<tr v-if="doc.total_discount_amount > 0">
						<td></td>
						<td class="pb-2 pr-2 pt-4 text-right font-semibold">
							Total Without Discount
						</td>
						<td
							class="whitespace-nowrap pb-2 pr-2 pt-4 text-right font-semibold"
						>
							{{ doc.formatted.total_before_discount }}
						</td>
					</tr>
					<tr v-if="doc.total_discount_amount > 0">
						<td></td>
						<td class="pb-2 pr-2 pt-4 text-right font-semibold">
							Total Discount Amount
						</td>
						<td
							class="whitespace-nowrap pb-2 pr-2 pt-4 text-right font-semibold"
						>
							{{
								doc.partner_email && doc.partner_email != doc.team
									? 0
									: doc.formatted.total_discount_amount
							}}
						</td>
					</tr>
					<tr v-if="doc.gst > 0">
						<td></td>
						<td class="pb-2 pr-2 pt-4 text-right font-semibold">
							Total (Without Tax)
						</td>
						<td
							class="whitespace-nowrap pb-2 pr-2 pt-4 text-right font-semibold"
						>
							{{ doc.formatted.total_before_tax }}
						</td>
					</tr>
					<tr v-if="doc.gst > 0">
						<td></td>
						<td class="pb-2 pr-2 pt-4 text-right font-semibold">
							IGST @ {{ Number($account.billing_info.gst_percentage * 100) }}%
						</td>
						<td
							class="whitespace-nowrap pb-2 pr-2 pt-4 text-right font-semibold"
						>
							{{ doc.formatted.gst }}
						</td>
					</tr>
					<tr>
						<td></td>
						<td class="pb-2 pr-2 pt-4 text-right font-semibold">Grand Total</td>
						<td
							class="whitespace-nowrap pb-2 pr-2 pt-4 text-right font-semibold"
						>
							{{
								doc.partner_email && doc.partner_email != doc.team
									? doc.formatted.total_before_discount
									: doc.formatted.total
							}}
						</td>
					</tr>
					<template v-if="doc.total !== doc.amount_due && doc.docstatus == 1">
						<tr>
							<td></td>
							<td class="pr-2 text-right">Applied Balance:</td>
							<td class="whitespace-nowrap py-3 pr-2 text-right font-semibold">
								- {{ doc.formatted.applied_credits }}
							</td>
						</tr>
						<tr>
							<td></td>
							<td class="pr-2 text-right">Amount Due:</td>
							<td class="whitespace-nowrap py-3 pr-2 text-right font-semibold">
								{{ doc.formatted.amount_due }}
							</td>
						</tr>
					</template>
				</tfoot>
			</table>
		</div>
		<div class="py-20 text-center" v-if="$resources.doc.loading">
			<Button :loading="true">Loading</Button>
		</div>
	</div>
</template>
<script>
export default {
	name: 'InvoiceUsageTable',
	props: ['invoice', 'invoiceDoc'],
	resources: {
		doc() {
			return {
				url: 'press.api.billing.get_invoice_usage',
				params: { invoice: this.invoice },
				auto: this.invoice,
				onSuccess(doc) {
					this.$emit('doc', doc);
				}
			};
		}
	},
	watch: {
		invoice(value) {
			if (value) {
				this.$resources.doc.fetch();
			}
		}
	},
	computed: {
		doc() {
			return this.invoiceDoc || this.$resources.doc.data;
		}
	}
};
</script>
